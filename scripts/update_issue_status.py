import os
import json
from github import Github
from typing import Optional


def read_teams_config() -> Optional[str]:
    """Read and return the teams configuration file content."""
    try:
        with open("teams.yml", "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, IOError) as e:
        raise RuntimeError("Error reading teams.yml file") from e


def update_issue_with_status() -> None:
    """Update GitHub issue with team configuration status."""
    # Get environment variables
    github_token = os.getenv("GITHUB_TOKEN")
    issue_payload = json.loads(os.getenv("ISSUE_PAYLOAD", "{}"))
    org_name = os.getenv("GITHUB_ORGANIZATION")

    if not all([github_token, issue_payload, org_name]):
        raise EnvironmentError("Required environment variables are missing.")

    # Initialize GitHub client and get issue
    g = Github(github_token)
    repo = g.get_repo(f"{org_name}/{issue_payload['repository']['name']}")
    issue = repo.get_issue(number=issue_payload["number"])

    # Get teams configuration
    teams_config = read_teams_config()

    # Create formatted comment with proper Markdown
    comment = f"""### ✅ Team Setup Complete
                
                The default team configuration has been successfully created and committed to the repository.
                
                #### Current Configuration
                
                ```yaml
                {teams_config}
                ```
                ####Next Steps - Update Team Settings
                
                You can update this configuration in two ways:
                
                1. Using Issues (Recommended):
                - Create a new issue with label team_update
                - Use the "Update Team Configuration" template
                - Fill in the settings you want to modify
                
                1. Direct YAML Edit:
                
                - Create a pull request modifying the teams.yml file
                - Changes will be reviewed and processed
                
                Available Update Options:
                
                - 👥 Team Members: Add or remove members
                - 🔒 Permissions: Modify repository access levels
                - 📝 Description: Update team description
                - 🔗 Repository Access: Add/remove repository access
                - 👨‍👩‍👧‍👦 Team Structure: Configure parent/child relationships
                
                The changes will be automatically processed and synced once approved."""
    
    # Create comment on issue
    try:
        issue.create_comment(comment)
    except Exception as e:
        raise RuntimeError(f"Failed to create issue comment: {str(e)}") from e

def main():
    # Call the function to update the GitHub issue with the team configuration status
    update_issue_with_status()


if __name__ == "__main__":
    main()