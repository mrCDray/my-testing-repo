import os
import json
import yaml
import logging
from github import Github, GithubException
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IssueBot:
    def __init__(self, token: str, repo_name: str):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        self.commands = {
            "create_team": self.handle_team_creation,
            "update_team": self.handle_team_update,
            "create_repo": self.handle_repo_creation,
            "update_repo": self.handle_repo_update,
        }

    def parse_issue_content(self, body: str) -> Dict[str, Any]:
        """Parse issue content into structured data"""
        data = {}
        current_section = None
        content = []

        for line in body.split("\n"):
            if line.startswith("### "):
                if current_section:
                    data[current_section] = "\n".join(content).strip()
                current_section = line.replace("### ", "").strip()
                content = []
            elif current_section:
                content.append(line)

        if current_section:
            data[current_section] = "\n".join(content).strip()

        return data

    def validate_input(self, data: Dict[str, Any], template_type: str) -> List[str]:
        """Validate user input against required fields"""
        errors = []
        required_fields = {"create_team": ["Team Name", "Members"], "create_repo": ["Repository Name", "Visibility"]}

        for field in required_fields.get(template_type, []):
            if not data.get(field) or data[field].strip() == "":
                errors.append(f"Missing required field: {field}")

        return errors

    def handle_issue_command(self, issue_number: int) -> None:
        """Process commands from issue"""
        try:
            issue = self.repo.get_issue(issue_number)
            body = issue.body.lower()
            command = next((cmd for cmd in self.commands if f"/{cmd}" in body), None)

            if command:
                self.commands[command](issue)
            elif "/help" in body:
                self.show_help_menu(issue)
            else:
                # Check if this is a form response
                if any(label.name in ["team_setup", "repo_setup"] for label in issue.labels):
                    self.process_form_response(issue)
                else:
                    self.show_help_menu(issue)

        except Exception as e:
            logger.error(f"Error processing issue: {str(e)}")
            issue.create_comment(f"❌ Error: {str(e)}")


    def handle_team_creation(self, issue) -> None:
        """Handle team creation request"""
        template = self.create_form_template("create_team")
        issue.edit(
            title=f"Team Creation: {issue.title}",
            body="\n".join(template["body"]),
            labels=["team_setup"]
        )

    def handle_repo_creation(self, issue) -> None:
        """Handle repository creation request"""
        template = self.create_form_template("create_repo")
        issue.edit(
            title=f"Repository Creation: {issue.title}",
            body="\n".join(template["body"]),
            labels=["repo_setup"]
        )


    def process_form_response(self, issue) -> None:
        """Process completed form response"""
        try:
            data = self.parse_issue_content(issue.body)
            template_type = "create_team" if "team_setup" in [l.name for l in issue.labels] else "create_repo"

            # Validate input
            errors = self.validate_input(data, template_type)
            if errors:
                error_message = "❌ Validation errors:\n" + "\n".join(f"- {e}" for e in errors)
                issue.create_comment(error_message)
                return

            # Create configuration file
            config = self.create_config_file(data, template_type)
            if config:
                issue.create_comment("✅ Configuration created successfully. Workflow started.")
            else:
                issue.create_comment("❌ Error creating configuration.")

        except Exception as e:
            logger.error(f"Error processing form: {str(e)}")
            issue.create_comment(f"❌ Error: {str(e)}")

    def create_config_file(self, data: Dict[str, Any], template_type: str) -> bool:
        """Create configuration file from form data"""
        try:
            if template_type == "create_team":
                config = {
                    "team": {
                        "name": data.get("Team Name", "").strip(),
                        "description": data.get("Description", "").strip(),
                        "members": [m.strip() for m in data.get("Members", "").split(",") if m.strip()],
                        "permission": data.get("Repository Permissions", "read").lower(),
                    }
                }
                path = f"teams/{config['team']['name'].lower()}/config.yml"
            else:
                config = {
                    "repository": {
                        "name": data.get("Repository Name", "").strip(),
                        "visibility": data.get("Visibility", "private").lower(),
                        "teams": [t.strip() for t in data.get("Team Access", "").split(",") if t.strip()],
                    }
                }
                path = f"repositories/{config['repository']['name'].lower()}.yml"

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                yaml.dump(config, f, default_flow_style=False)

            return True

        except Exception as e:
            logger.error(f"Error creating config file: {str(e)}")
            return False


if __name__ == "__main__":
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("REPO_NAME")
    issue_number = int(os.environ.get("ISSUE_NUMBER"))

    if not all([token, repo_name, issue_number]):
        logger.error("Missing required environment variables")
        exit(1)

    bot = IssueBot(token, repo_name)
    bot.handle_issue_command(issue_number)
