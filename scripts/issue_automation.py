import os
import json
import yaml
from github import Github, GithubException
from typing import Dict, List, Any


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

    def create_form_template(self, command: str) -> Dict[str, Any]:
        """Generate form template based on command"""
        templates = {
            "create_team": {
                "title": "Team Creation Request",
                "body": [
                    "### Team Name",
                    "Enter team name:",
                    "",
                    "### Project",
                    "Enter project name:",
                    "",
                    "### Description",
                    "Enter team description:",
                    "",
                    "### Members",
                    "List team members (comma-separated):",
                    "",
                    "### Repository Permissions",
                    "Select permission level:",
                    "- [ ] read",
                    "- [ ] write",
                    "- [ ] admin",
                ],
            },
            "create_repo": {
                "title": "Repository Creation Request",
                "body": [
                    "### Repository Name",
                    "Enter repository name:",
                    "",
                    "### Visibility",
                    "Select visibility:",
                    "- [ ] private",
                    "- [ ] internal",
                    "",
                    "### Team Access",
                    "List teams that need access (comma-separated):",
                    "",
                    "### Configuration",
                    "```yaml",
                    "repository:",
                    "  has_issues: true",
                    "  has_projects: true",
                    "  has_wiki: true",
                    "```",
                ],
            },
        }
        return templates.get(command, {})

    def handle_issue_command(self, issue_number: int) -> None:
        """Process commands from issue"""
        issue = self.repo.get_issue(issue_number)
        body = issue.body.lower()

        if "/help" in body:
            self.show_help_menu(issue)
            return

        for command in self.commands:
            if f"/{command}" in body:
                self.commands[command](issue)
                return

        self.show_help_menu(issue)

    def show_help_menu(self, issue) -> None:
        """Display help menu with available commands"""
        menu = [
            "## Available Commands",
            "",
            "- `/create_team` - Start team creation workflow",
            "- `/update_team` - Start team update workflow",
            "- `/create_repo` - Start repository creation workflow",
            "- `/update_repo` - Start repository update workflow",
            "- `/help` - Show this help menu",
            "",
            "To use a command, create a new issue with the command as the first line.",
        ]
        issue.create_comment("\n".join(menu))

    def handle_team_creation(self, issue) -> None:
        """Handle team creation request"""
        template = self.create_form_template("create_team")
        issue.edit(title=f"Team Creation: {issue.title}", body="\n".join(template["body"]), labels=["team_setup"])

    def handle_repo_creation(self, issue) -> None:
        """Handle repository creation request"""
        template = self.create_form_template("create_repo")
        issue.edit(title=f"Repository Creation: {issue.title}", body="\n".join(template["body"]), labels=["repo_setup"])
