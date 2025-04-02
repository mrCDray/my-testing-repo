import os
import sys
from pathlib import Path
import logging
import traceback
from typing import List, Dict, Optional
import yaml
from github import Github, GithubException, Issue, Repository


def setup_logging():
    """Configure logging for script"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    return logging.getLogger(__name__)


def normalize_username(username: str) -> str:
    """Remove @ prefix and quotes from username if present"""
    return "" if username is None else username.lstrip("@").strip("'")


def find_team_config_file(team_name: str) -> Optional[Path]:
    """Find the teams.yml file for a specific team"""
    teams_dir = Path("teams")
    for team_file in teams_dir.glob("*/teams.yml"):
        try:
            with open(team_file, mode="r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                if config.get("teams", {}).get("team_name") == team_name:
                    return team_file
        except Exception:
            continue
    return None


def update_team_config_file(team_name: str, members: List[str], operation: str) -> bool:
    """
    Update the teams.yml file for a given team

    :param team_name: Name of the team to update
    :param members: List of usernames to add/remove
    :param operation: 'add', 'remove', or 'sync'
    :return: True if file was successfully updated, False otherwise
    """
    team_config_file = find_team_config_file(team_name)
    if not team_config_file:
        logging.error(f"Could not find configuration file for team {team_name}")
        return False

    try:
        # Read the existing configuration
        with open(team_config_file, mode="r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Normalize existing and new members
        existing_members = config["teams"].get("members", [])
        normalized_existing = [normalize_username(m) for m in existing_members]
        normalized_new = [normalize_username(m) for m in members]

        # Determine updated member list based on operation
        if operation == "add":
            # Add members that don't already exist
            updated_members = existing_members + [
                m for m in members if normalize_username(m) not in normalized_existing
            ]
        elif operation == "remove":
            # Remove specified members
            updated_members = [m for m in existing_members if normalize_username(m) not in normalized_new]
        elif operation == "sync":
            # Replace existing members with new list
            updated_members = members
        else:
            logging.error(f"Invalid operation: {operation}")
            return False

        # Update the configuration
        config["teams"]["members"] = updated_members

        # Also update sub-teams if they exist
        if "default_sub_teams" in config["teams"]:
            for sub_team in config["teams"]["default_sub_teams"]:
                # Find and update sub-team members if specified in the issue
                sub_team_name = sub_team["name"]

                # Check if the sub-team should be updated
                if any(normalize_username(m).startswith(sub_team_name.split("-")[-1]) for m in members):
                    # Update sub-team members with the same logic
                    if operation == "add":
                        existing_sub_members = sub_team.get("members", [])
                        sub_team["members"] = existing_sub_members + [
                            m
                            for m in members
                            if m not in existing_sub_members
                            and normalize_username(m).startswith(sub_team_name.split("-")[-1])
                        ]
                    elif operation == "remove":
                        sub_team["members"] = [
                            m for m in sub_team.get("members", []) if normalize_username(m) not in normalized_new
                        ]
                    elif operation == "sync":
                        sub_team["members"] = [
                            m for m in members if normalize_username(m).startswith(sub_team_name.split("-")[-1])
                        ]

        # Write back to the file
        with open(team_config_file, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False)

        return True

    except Exception as e:
        logging.error(f"Error updating team configuration file: {e}")
        return False


def parse_issue_body(issue: Issue) -> Optional[Dict]:
    """
    Parse GitHub Issue body for team configuration commands.

    Expected issue body format:
    ```
    /teams
    team: team-name
    operation: add|remove|sync
    members:
    - username1
    - username2
    ```
    """
    lines = issue.body.split("\n")

    # Check for /teams command
    if not lines or lines[0].strip() != "/teams":
        return None

    config = {}
    current_section = None

    for line in lines[1:]:
        line = line.strip()

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if key == "team":
                config["team"] = value
            elif key == "operation":
                config["operation"] = value.lower()

            current_section = key
        elif current_section == "members" and line.startswith("- "):
            config.setdefault("members", []).append(line[2:].strip())

    # Validate configuration
    if any(key not in config for key in ["team", "operation"]):
        return None

    return config


def sync_team_membership(gh, org, team_slug: str, members: List[str], logger: logging.Logger) -> Dict:
    """
    Sync team membership, ensuring precise alignment with desired members.
    Returns a dictionary with details of changes made.
    """
    try:
        team = org.get_team_by_slug(team_slug)
        current_members = {member.login for member in team.get_members()}
        desired_members = {normalize_username(member) for member in members}

        changes = {"added": [], "removed": [], "already_members": [], "not_found": []}

        # Add new members
        for member in desired_members - current_members:
            try:
                user = gh.get_user(member)
                team.add_membership(user, role="member")
                changes["added"].append(member)
                logger.info(f"Added {member} to {team_slug}")
            except GithubException as e:
                if "User not found" in str(e):
                    changes["not_found"].append(member)
                else:
                    logger.error(f"Failed to add {member} to {team_slug}: {e}")

        # Remove extra members
        for member in current_members - desired_members:
            try:
                user = gh.get_user(member)
                team.remove_membership(user)
                changes["removed"].append(member)
                logger.info(f"Removed {member} from {team_slug}")
            except GithubException as e:
                logger.error(f"Failed to remove {member} from {team_slug}: {e}")

        # Track already existing members
        changes["already_members"] = list(current_members & desired_members)

        return changes

    except GithubException as e:
        logger.error(f"Failed to sync team {team_slug}: {e}")
        return {"added": [], "removed": [], "already_members": [], "not_found": [], "error": str(e)}


def process_team_configuration_issue(gh, org, issue: Issue, logger: logging.Logger):
    """Process team configuration changes from a GitHub Issue"""
    config = parse_issue_body(issue)
    if not config:
        issue.create_comment("❌ Invalid team configuration format. Please use the correct YAML-like syntax.")
        return False

    try:
        # Validate team exists
        try:
            org.get_team_by_slug(config["team"])
        except GithubException:
            issue.create_comment(f"❌ Team {config['team']} not found in the organization.")
            return False

        members = [normalize_username(member) for member in config.get("members", [])]
        operation = config["operation"]

        # Update the configuration file first
        file_update_success = update_team_config_file(config["team"], members, operation)
        if not file_update_success:
            issue.create_comment("❌ Failed to update team configuration file.")
            return False

        # Prepare changes based on operation type
        if operation in ["add", "remove", "sync"]:
            # Sync team membership
            changes = sync_team_membership(gh, org, config["team"], members, logger)

            # Prepare a detailed comment about changes
            comment_parts = []

            if file_update_success:
                comment_parts.append("✅ Team configuration file updated successfully")

            if changes["added"]:
                comment_parts.append(f"✅ Added members: {', '.join(changes['added'])}")

            if changes["removed"]:
                comment_parts.append(f"✅ Removed members: {', '.join(changes['removed'])}")

            if changes["not_found"]:
                comment_parts.append(f"⚠️ Users not found: {', '.join(changes['not_found'])}")

            if "error" in changes:
                comment_parts.append(f"❌ Sync error: {changes['error']}")

            # Create a comprehensive comment
            if comment_parts:
                issue.create_comment("\n".join(comment_parts))
            else:
                issue.create_comment(f"ℹ️ No changes needed for team {config['team']}")

        else:
            issue.create_comment(f"❌ Invalid operation '{operation}'. Use 'add', 'remove', or 'sync'.")
            return False

        # Close the issue after processing
        issue.edit(state="closed")
        return True

    except Exception as e:
        logger.error(f"Error processing team configuration issue: {e}")
        issue.create_comment(f"❌ Error processing team configuration: {str(e)}")
        return False


def process_issue_ops(gh, org, repo: Repository, logger: logging.Logger):
    """Process team membership configuration issues"""
    # Find open issues with /teams command
    issues = repo.get_issues(state="open", labels=["team_user_maintain"])

    for issue in issues:
        try:
            process_team_configuration_issue(gh, org, issue, logger)
        except Exception as e:
            logger.error(f"Failed to process issue #{issue.number}: {e}")


def main():
    logger = setup_logging()

    github_token = os.environ.get("GITHUB_TOKEN")
    org_name = os.environ.get("GITHUB_ORGANIZATION")
    if not all([org_name, github_token]):
        logger.error("GITHUB_TOKEN/GITHUB_ORGANIZATION environment variable is not set")
        return 1

    try:
        gh = Github(github_token)
        org = gh.get_organization(org_name)

        # Determine if this is a workflow triggered by an issue
        if os.getenv("GITHUB_EVENT_NAME") == "issues":
            repo_full_name = os.environ.get("GITHUB_REPOSITORY")
            if not repo_full_name:
                logger.error("Missing repository information")
                return 1

            repo = gh.get_repo(repo_full_name)
            process_issue_ops(gh, org, repo, logger)

        return 0

    except Exception as e:
        logger.error(f"Unexpected error in main: {str(e)}\n{traceback.format_exc()}")
        return 1
    finally:
        gh.close()


if __name__ == "__main__":
    sys.exit(main())
