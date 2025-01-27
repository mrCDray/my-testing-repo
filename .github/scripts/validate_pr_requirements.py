import os
import sys
import json
import yaml
from github import Github, GithubException


def get_pr_number():
    """Retrieve PR number from various possible sources."""
    pr_number_env = os.environ.get("PR_NUMBER")
    if pr_number_env:
        return int(pr_number_env)

    github_event_path = os.environ.get("GITHUB_EVENT_PATH")
    if github_event_path and os.path.exists(github_event_path):
        with open(github_event_path, mode="r", encoding="utf-8") as event_file:
            event_data = json.load(event_file)
            if "pull_request" in event_data:
                return event_data["pull_request"]["number"]
            if "number" in event_data:
                return event_data["number"]

    raise ValueError("Could not determine PR number. Ensure PR_NUMBER is set or running in a GitHub Actions context.")


def replace_placeholders(text, team_name):
    """Replace team name placeholders in the configuration."""
    return text.replace("{{ team_name }}", team_name)


def expand_team_members(github_obj, org, teams):
    """Expand team members from GitHub teams."""
    team_members = set()  # Using set to avoid duplicates
    org_obj = github_obj.get_organization(org)
    print(f"Organization: {org}")

    # List all teams in organization for debugging
    try:
        all_teams = list(org_obj.get_teams())
        print(f"Available teams in org: {[team.slug for team in all_teams]}")
    except GithubException as e:
        print(f"Error listing organization teams: {e}")

    for team_name in teams:
        print(f"\nProcessing team: {team_name}")
        try:
            # Try to get team directly first
            team = org_obj.get_team_by_slug(team_name.lower())  # GitHub team slugs are lowercase
            print(f"Found team: {team.name}")

            # List and add team members
            members = list(team.get_members())
            print(f"Team members found: {[member.login for member in members]}")
            team_members.update(member.login for member in members)

        except GithubException as e:
            print(f"Error accessing team {team_name}: {e}")
            if e.status == 404:
                print(f"Team not found: {team_name}. Make sure the team exists and the token has proper permissions.")
            else:
                print(f"Unexpected error accessing team: {e.data.get('message', str(e))}")

    return list(team_members)


def validate_pr_requirements(config_path, pr_number, target_branch, team_name, github_token):
    """Validate pull request review requirements."""
    print("Starting validation")

    # Load configuration
    try:
        with open(config_path, mode="r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except Exception as e:
        print(f"Error loading config file {config_path}: {e}")
        return False

    # Initialize GitHub client
    github_obj = Github(github_token)
    repo = github_obj.get_repo(os.environ.get("GITHUB_REPOSITORY"))

    try:
        pull_request = repo.get_pull(pr_number)
    except GithubException as e:
        print(f"Error accessing PR #{pr_number}: {e}")
        return False

    # Find branch-specific configuration
    branch_configs = config["pull_requests"]["branches"]
    branch_config = None

    print(f"Looking for configuration matching branch: {target_branch}")
    for pattern, cfg in branch_configs.items():
        pattern_clean = pattern.replace("*", "")
        if pattern == target_branch or (pattern.endswith("*") and target_branch.startswith(pattern_clean)):
            if not (cfg.get("exclude") and target_branch in cfg["exclude"]):
                branch_config = cfg
                print(f"Found matching configuration for pattern: {pattern}")
                break

    if not branch_config:
        print(f"No configuration found for branch {target_branch}")
        return False

    # Get required approvals count
    required_approvals = int(branch_config.get("required_approvals", 0))
    print(f"Required approvals: {required_approvals}")

    # Get required teams and their members
    required_teams = [replace_placeholders(team, team_name) for team in branch_config.get("required_teams", [])]
    print(f"Required teams: {required_teams}")

    required_team_members = expand_team_members(github_obj, repo.organization.login, required_teams)
    if not required_team_members:
        print("Warning: No team members found. This might indicate a configuration or permissions issue.")
    print(f"Required team members: {required_team_members}")

    # Get all reviews
    try:
        reviews = list(pull_request.get_reviews())
        print(f"Found {len(reviews)} reviews")
    except GithubException as e:
        print(f"Error accessing PR reviews: {e}")
        return False

    # Get the latest review state from each reviewer
    latest_reviews = {}
    for review in reviews:
        latest_reviews[review.user.login] = review.state

    print(f"Latest review states: {latest_reviews}")

    # Count valid approvals from required team members
    valid_approvals = sum(1 for member in required_team_members if latest_reviews.get(member) == "APPROVED")

    print(f"Valid approvals received: {valid_approvals}")

    # Check if we have any required team members before validation
    if not required_team_members:
        print("Cannot validate: No required team members found")
        return False

    # Validate against both required approvals count and required team members
    is_valid = valid_approvals >= required_approvals and valid_approvals >= len(required_team_members)

    print(f"Validation result: {is_valid}")
    return is_valid


def main():
    try:
        print("Starting PR requirements validation...")
        # Get environment variables
        config_path = os.environ.get("REVIEWERS_CONFIG_PATH", "REVIEWERS.yml")
        team_name = os.environ.get("TEAM_NAME")
        github_token = os.environ.get("GITHUB_TOKEN")
        target_branch = os.environ.get("TARGET_BRANCH", os.environ.get("GITHUB_BASE_REF", ""))

        print(f"Target Branch: {target_branch}")
        print(f"Team Name: {team_name}")
        print(f"Config Path: {config_path}")

        # Get PR number
        print("getting PR number")
        pr_number = int(get_pr_number())
        print(f"PR Number: {pr_number}")

        # Validate PR requirements
        result = validate_pr_requirements(config_path, pr_number, target_branch, team_name, github_token)

        # Print result for workflow
        print(f"Validation result: {result}")

        # Use the new GitHub Actions output syntax
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            print(f"status={str(result).lower()}", file=fh)

        # Exit with appropriate status code
        sys.exit(0 if result else 1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
