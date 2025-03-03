import os
import re
from typing import Dict, List, Optional, Set
import yaml
from github import Github
from github.GithubException import GithubException


class PRReviewManager:
    def __init__(self, github_token: str, repository: str, pr_number: int):
        """Initialize the PR Review Manager."""
        self.gh = Github(github_token)
        self.repo = self.gh.get_repo(repository)
        self.pr_number = pr_number
        self.pr = self.repo.get_pull(pr_number)
        self.config = self._load_config()
        self.org = self.repo.organization
        # Cache for team members to avoid repeated API calls
        self._team_members_cache = {}
        # Cache for user teams to avoid repeated API calls
        self._user_teams_cache = {}

    def _load_config(self) -> Dict:
        """Load the REVIEWERS.yml configuration file from PR's head branch."""
        try:
            # Try to get the file from the PR's head branch first
            try:
                config_file = self.repo.get_contents("REVIEWERS.yml", ref=self.pr.head.ref)
                print(f"Debug: Found REVIEWERS.yml in PR head branch {self.pr.head.ref}")
            except Exception as e:
                # Fallback to the base branch
                config_file = self.repo.get_contents("REVIEWERS.yml", ref=self.pr.base.ref)
                print(f"Debug: Found REVIEWERS.yml in base branch {self.pr.base.ref}")

            content = config_file.decoded_content
            if not content:
                raise ValueError("REVIEWERS.yml is empty")

            config = yaml.safe_load(content.decode("utf-8"))
            if not config:
                raise ValueError("REVIEWERS.yml contains no valid configuration")

            return config

        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse REVIEWERS.yml: {str(e)}") from e
        except Exception as e:
            raise FileNotFoundError(f"Failed to load REVIEWERS.yml: {str(e)}") from e

    def _get_branch_config(self, branch_name: str) -> Optional[Dict]:
        """Get the configuration for a specific branch."""
        try:
            branch_configs = self.config["pull_requests"]["branches"]

            # First check for exact match
            if branch_name in branch_configs:
                return branch_configs[branch_name]

            # Then check pattern matches
            for pattern, config in branch_configs.items():
                if "*" in pattern:
                    regex_pattern = "^" + pattern.replace("*", ".*") + "$"
                    if re.match(regex_pattern, branch_name):
                        # Check if branch is excluded
                        if "exclude" in config and branch_name in config["exclude"]:
                            continue
                        return config

            return None

        except KeyError:
            return None
        except Exception as e:
            print(f"Debug: Error getting branch configuration: {str(e)}")
            return None

    def _get_team_members(self, team_slug: str, org) -> List[str]:
        """Get list of usernames for members of a team with caching."""
        if team_slug in self._team_members_cache:
            return self._team_members_cache[team_slug]

        try:
            team = org.get_team_by_slug(team_slug)
            members = list(team.get_members())
            if not members:
                print(f"Warning: No members found in team {team_slug}")
                self._team_members_cache[team_slug] = []
                return []

            member_logins = [member.login for member in members]
            self._team_members_cache[team_slug] = member_logins
            return member_logins

        except GithubException as e:
            if e.status == 404:
                print(f"Warning: Team {team_slug} not found")
            else:
                print(f"Warning: Error accessing team {team_slug}: {str(e)}")
            self._team_members_cache[team_slug] = []
            return []
        except Exception as e:
            print(f"Warning: Unexpected error getting team members for {team_slug}: {str(e)}")
            self._team_members_cache[team_slug] = []
            return []

    def _get_user_teams(self, username: str, required_team_slugs: List[str], org) -> List[str]:
        """
        Get the teams a user belongs to, but only check the required teams.
        This avoids checking all teams in the organization.
        """
        if username in self._user_teams_cache:
            return self._user_teams_cache[username]

        try:
            user_teams = []
            user_obj = self.gh.get_user(username)

            # Only check the required teams instead of all teams in the org
            for team_slug in required_team_slugs:
                try:
                    team = org.get_team_by_slug(team_slug)
                    if team.has_in_members(user_obj):
                        user_teams.append(team_slug)
                except Exception as e:
                    print(f"Warning: Error checking if user {username} is in team {team_slug}: {str(e)}")
                    continue

            self._user_teams_cache[username] = user_teams
            return user_teams

        except Exception as e:
            print(f"Warning: Error getting teams for user {username}: {str(e)}")
            self._user_teams_cache[username] = []
            return []

    def _check_branch_protection(self, branch_name: str) -> bool:
        """Check if the branch has 'dismiss stale reviews' enabled in branch protection."""
        try:
            branch = self.repo.get_branch(branch_name)
            protection = branch.get_protection()
            return protection.required_pull_request_reviews.dismiss_stale_reviews
        except Exception as e:
            print(f"Warning: Could not check branch protection settings: {str(e)}")
            return False

    def _format_team_slug(self, team_name: str) -> str:
        """Format a team name into a proper team slug with variable substitution."""
        team_name = team_name.replace("{{ team_name }}", os.environ.get("TEAM_NAME", ""))
        return team_name.lower().strip().replace(" ", "-")

    def _check_required_reviews(self, pr, branch_config: Dict, org) -> bool:
        """Check if the PR has met the required review conditions."""
        try:
            required_approvals = branch_config.get("required_approvals", 0)
            required_teams = branch_config.get("required_teams", [])

            # Early return if no requirements
            if required_approvals == 0 and not required_teams:
                return True

            # Format required team slugs once
            required_team_slugs = [self._format_team_slug(team) for team in required_teams] if required_teams else []

            # Get all reviews
            reviews = list(pr.get_reviews())
            approved_reviewers = set()
            # Use a set to track which required teams have approvals
            approved_teams = set()

            # Process only the most recent review from each reviewer
            reviewer_latest_review = {}
            for review in reviews:
                reviewer = review.user.login
                # Only track if we haven't seen this reviewer or if this review is newer
                if (
                    reviewer not in reviewer_latest_review
                    or reviewer_latest_review[reviewer].created_at < review.created_at
                ):
                    reviewer_latest_review[reviewer] = review

            # Now process only the latest review from each reviewer
            for reviewer, review in reviewer_latest_review.items():
                if review.state == "APPROVED":
                    approved_reviewers.add(reviewer)

                    # Only check team membership if we have required teams
                    if required_team_slugs:
                        # Get teams for this user, but only check required teams
                        user_teams = self._get_user_teams(reviewer, required_team_slugs, org)
                        approved_teams.update(user_teams)

            # Check number of approvals
            if len(approved_reviewers) < required_approvals:
                print(f"Debug: Not enough approvals. Got {len(approved_reviewers)}, need {required_approvals}")
                return False

            # Check required teams
            if required_team_slugs:
                missing_teams = set(required_team_slugs) - approved_teams
                if missing_teams:
                    print(f"Debug: Missing required team approvals from: {missing_teams}")
                    return False

            return True

        except Exception as e:
            print(f"Warning: Error checking required reviews: {str(e)}")
            return False

    def process_pull_request(self, pr_number: int, org):
        """Process a pull request according to the configuration."""
        pr = self.repo.get_pull(pr_number)
        branch_name = pr.base.ref
        print(f"Debug: Processing PR #{pr_number} targeting branch {branch_name}")

        branch_config = self._get_branch_config(branch_name)
        if not branch_config:
            print(f"No configuration found for branch: {branch_name}")
            return

        # Check if stale reviews are dismissed for this branch
        dismiss_stale_reviews = self._check_branch_protection(branch_name)

        # Count reviews once
        reviews_count = list(pr.get_reviews())

        # Only add new reviewers if no reviews exist or if stale reviews are dismissed
        should_request_reviews = dismiss_stale_reviews or len(reviews_count) == 0

        # Assign reviewers and assignees
        review_teams = branch_config.get("review_teams", [])
        assignee_teams = branch_config.get("assignees", [])

        try:
            # Add review teams using team slugs if needed
            if should_request_reviews and review_teams:
                formatted_review_teams = [self._format_team_slug(team) for team in review_teams]
                # Request reviews in a single batch when possible
                try:
                    pr.create_review_request(team_reviewers=formatted_review_teams)
                    print(f"Successfully requested reviews from teams: {', '.join(formatted_review_teams)}")
                except GithubException as e:
                    # Fall back to individual requests if batch fails
                    print(f"Warning: Batch review request failed, trying individual requests: {str(e)}")
                    for team_slug in formatted_review_teams:
                        try:
                            pr.create_review_request(team_reviewers=[team_slug])
                            print(f"Successfully requested review from team: {team_slug}")
                        except GithubException as e:
                            print(f"Warning: Could not request review from team {team_slug}: {str(e)}")

            # Add assignees from teams - collect all first, then add in one operation
            if assignee_teams:
                assignees = set()
                formatted_assignee_teams = [self._format_team_slug(team) for team in assignee_teams]

                for team_slug in formatted_assignee_teams:
                    team_members = self._get_team_members(team_slug, org)
                    assignees.update(team_members)

                # Only proceed if there are assignees to add
                if assignees:
                    # Add assignees in batches to handle GitHub's limitation
                    assignees_list = list(assignees)
                    for i in range(0, len(assignees_list), 10):
                        batch = assignees_list[i : i + 10]
                        pr.add_to_assignees(*batch)
                        print(f"Successfully added assignees: {', '.join(batch)}")
                else:
                    print("No valid assignees found to add to the PR")

            # Check review requirements
            meets_requirements = self._check_required_reviews(pr, branch_config, org)

            # Update status check
            status_context = "pr-review-requirements"
            try:
                commit = self.repo.get_commit(pr.head.sha)
                if not meets_requirements:
                    commit.create_status(
                        state="pending",
                        target_url="",
                        description="Required reviews not yet met",
                        context=status_context,
                    )
                else:
                    commit.create_status(
                        state="success",
                        target_url="",
                        description="All review requirements met",
                        context=status_context,
                    )
            except GithubException as e:
                print(f"Warning: Could not update status check: {str(e)}")

        except Exception as e:
            print(f"Error processing PR #{pr_number}: {str(e)}")
            raise


def main():
    # Get inputs from GitHub Actions environment
    github_token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])
    org_name = os.environ["GITHUB_ORGANIZATION"]

    # Initialize and run the PR Review Manager
    gh = Github(github_token)
    org = gh.get_organization(org_name)
    manager = PRReviewManager(github_token, repository, pr_number)
    manager.process_pull_request(pr_number, org)


if __name__ == "__main__":
    main()
