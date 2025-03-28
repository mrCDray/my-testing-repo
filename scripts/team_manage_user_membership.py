import os
import sys
import logging
import traceback
from typing import List, Dict, Optional
from github import Github, GithubException, Issue, Repository

def setup_logging():
    """Configure logging for script"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    return logging.getLogger(__name__)

def normalize_username(username: str) -> str:
    """Remove @ prefix and quotes from username if present"""
    return "" if username is None else username.lstrip("@").strip("'")

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
    lines = issue.body.split('\n')
    
    # Check for /teams command
    if not lines or lines[0].strip() != '/teams':
        return None
    
    config = {}
    current_section = None
    
    for line in lines[1:]:
        line = line.strip()
        
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()
            
            if key == 'team':
                config['team'] = value
            elif key == 'operation':
                config['operation'] = value.lower()
            
            current_section = key
        elif current_section == 'members' and line.startswith('- '):
            config.setdefault('members', []).append(line[2:].strip())
    
    # Validate configuration
    if any (key not in config for key in ['team', 'operation']):
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

        changes = {
            'added': [],
            'removed': [],
            'already_members': [],
            'not_found': []
        }

        # Add new members
        for member in desired_members - current_members:
            try:
                user = gh.get_user(member)
                team.add_membership(user, role="member")
                changes['added'].append(member)
                logger.info(f"Added {member} to {team_slug}")
            except GithubException as e:
                if 'User not found' in str(e):
                    changes['not_found'].append(member)
                else:
                    logger.error(f"Failed to add {member} to {team_slug}: {e}")

        # Remove extra members
        for member in current_members - desired_members:
            try:
                user = gh.get_user(member)
                team.remove_membership(user)
                changes['removed'].append(member)
                logger.info(f"Removed {member} from {team_slug}")
            except GithubException as e:
                logger.error(f"Failed to remove {member} from {team_slug}: {e}")

        # Track already existing members
        changes['already_members'] = list(current_members & desired_members)

        return changes

    except GithubException as e:
        logger.error(f"Failed to sync team {team_slug}: {e}")
        return {
            'added': [],
            'removed': [],
            'already_members': [],
            'not_found': [],
            'error': str(e)
        }

def process_team_configuration_issue(gh, org, issue: Issue, logger: logging.Logger):
    """Process team configuration changes from a GitHub Issue"""
    config = parse_issue_body(issue)
    if not config:
        issue.create_comment("❌ Invalid team configuration format. Please use the correct YAML-like syntax.")
        return False
    
    try:
        # Validate team exists
        try:
            org.get_team_by_slug(config['team'])
        except GithubException:
            issue.create_comment(f"❌ Team {config['team']} not found in the organization.")
            return False
        
        members = [normalize_username(member) for member in config.get('members', [])]
        operation = config['operation']
        
        # Prepare changes based on operation type
        if operation in ['add', 'remove']:
            # For add/remove, we'll always sync to ensure precise membership
            changes = sync_team_membership(gh, org, config['team'], members, logger)
            
            # Prepare a detailed comment about changes
            comment_parts = []
            
            if changes['added']:
                comment_parts.append(f"✅ Added members: {', '.join(changes['added'])}")
            
            if changes['removed']:
                comment_parts.append(f"✅ Removed members: {', '.join(changes['removed'])}")
            
            if changes['not_found']:
                comment_parts.append(f"⚠️ Users not found: {', '.join(changes['not_found'])}")
            
            if 'error' in changes:
                comment_parts.append(f"❌ Sync error: {changes['error']}")
            
            # Create a comprehensive comment
            if comment_parts:
                issue.create_comment('\n'.join(comment_parts))
            else:
                issue.create_comment(f"ℹ️ No changes needed for team {config['team']}")
        
        elif operation == 'sync':
            # Explicit sync operation
            changes = sync_team_membership(gh, org, config['team'], members, logger)
            
            # Prepare a detailed comment about sync results
            comment_parts = []
            
            if changes['added']:
                comment_parts.append(f"✅ Added members: {', '.join(changes['added'])}")
            
            if changes['removed']:
                comment_parts.append(f"✅ Removed members: {', '.join(changes['removed'])}")
            
            if changes['already_members']:
                comment_parts.append(f"ℹ️ Already members: {', '.join(changes['already_members'])}")
            
            if changes['not_found']:
                comment_parts.append(f"⚠️ Users not found: {', '.join(changes['not_found'])}")
            
            if 'error' in changes:
                comment_parts.append(f"❌ Sync error: {changes['error']}")
            
            # Create a comprehensive comment
            if comment_parts:
                issue.create_comment('\n'.join(comment_parts))
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
    issues = repo.get_issues(state='open', labels=['team-config'])
    
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