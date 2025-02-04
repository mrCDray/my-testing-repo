from github import Github
import yaml
import re
import os
from typing import Dict, Any, Optional, List, Tuple


class RepoIssueHandler:
    def __init__(self, token: str, org_name: str):
        self.github = Github(token)
        self.org = self.github.get_organization(org_name)
        self.default_config = self._load_default_config()

    def _load_default_config(self) -> Dict[str, Any]:
        """Load default repository configuration"""
        with open("default_repository.yml", "r") as f:
            return yaml.safe_load(f)

    def parse_issue_body(self, issue) -> Dict[str, Any]:
        """Parse issue body from the form-based template"""
        config = {"repository": {}, "security": {}, "rulesets": [], "custom_properties": []}

        # Get form data from issue body
        form_data = issue.body

        # Parse basic repository information
        config["repository"]["name"] = self._get_form_value(form_data, "repo-name")
        config["repository"]["visibility"] = self._get_form_value(form_data, "visibility")
        config["repository"]["description"] = self._get_form_value(form_data, "description")

        # Parse YAML configurations
        yaml_sections = {
            "repo-config": "repository",
            "security-settings": "security",
            "branch-protection": "rulesets",
            "custom-properties": "custom_properties",
        }

        for form_id, config_key in yaml_sections.items():
            yaml_text = self._extract_yaml_from_form(form_data, form_id)
            if yaml_text:
                try:
                    parsed_yaml = yaml.safe_load(yaml_text)
                    if config_key in parsed_yaml:
                        config[config_key].update(parsed_yaml[config_key])
                except yaml.YAMLError as e:
                    raise ValueError(f"Invalid YAML in {form_id}: {str(e)}")

        return config

    def _get_form_value(self, form_data: str, field_id: str) -> str:
        """Extract value from a form field"""
        pattern = f"### {field_id}\n\n(.*?)(?=###|$)"
        match = re.search(pattern, form_data, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _extract_yaml_from_form(self, form_data: str, field_id: str) -> Optional[str]:
        """Extract YAML content from a form field"""
        yaml_pattern = f"### {field_id}.*?```yaml\n(.*?)```"
        match = re.search(yaml_pattern, form_data, re.DOTALL)
        return match.group(1) if match else None

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate repository configuration against allowed values"""
        errors = []

        # Basic validation rules
        if "repository" in config:
            repo_config = config["repository"]

            # Validate visibility
            if "visibility" in repo_config:
                if repo_config["visibility"] not in ["internal", "private"]:
                    errors.append("Visibility must be either 'internal' or 'private'")

            # Validate branch name
            if "default_branch" in repo_config:
                if not re.match(r"^[a-zA-Z0-9_-]+$", repo_config["default_branch"]):
                    errors.append("Invalid default branch name")

        return len(errors) == 0, errors

    def handle_creation_issue(self, issue_number: int) -> None:
        """Handle repository creation issue"""
        try:
            issue = self.org.get_issue(issue_number)
            config = self.parse_issue_body(issue.body)

            # Validate configuration
            is_valid, errors = self.validate_config(config)
            if not is_valid:
                self._comment_on_issue(issue, "Configuration validation failed:\n" + "\n".join(errors))
                return

            # Create repository
            repo = self._create_repository(config)

            # Apply configuration
            self._apply_repository_config(repo, config)

            # Close issue with success message
            self._comment_on_issue(issue, f"Repository {repo.name} created successfully")
            issue.edit(state="closed")

        except Exception as e:
            self._comment_on_issue(issue, f"Error processing repository creation: {str(e)}")

    def handle_update_issue(self, issue_number: int) -> None:
        """Handle repository update issue"""
        try:
            issue = self.org.get_issue(issue_number)
            config = self.parse_issue_body(issue.body)

            # Validate configuration
            is_valid, errors = self.validate_config(config)
            if not is_valid:
                self._comment_on_issue(issue, "Configuration validation failed:\n" + "\n".join(errors))
                return

            # Get repository
            repo = self.org.get_repo(config["repository"]["name"])

            # Apply updates
            changes = self._apply_repository_config(repo, config)

            # Close issue with success message
            self._comment_on_issue(issue, f"Repository {repo.name} updated successfully:\n{yaml.dump(changes)}")
            issue.edit(state="closed")

        except Exception as e:
            self._comment_on_issue(issue, f"Error processing repository update: {str(e)}")

    def _create_repository(self, config: Dict[str, Any]):
        """Create new repository with basic settings"""
        repo_config = config["repository"]
        return self.org.create_repo(
            name=repo_config["name"],
            private=(repo_config["visibility"] == "private"),
            internal=(repo_config["visibility"] == "internal"),
            auto_init=True,
        )

    def _apply_repository_config(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply configuration to repository and return changes made"""
        changes = {}

        try:
            # Apply repository settings
            repo_config = config.get("repository", {})
            self._update_repo_settings(repo, repo_config, changes)

            # Apply branch protection
            if "rulesets" in config:
                self._update_branch_protection(repo, config["rulesets"], changes)

            # Apply custom properties
            if "custom_properties" in config:
                self._update_custom_properties(repo, config["custom_properties"], changes)

        except Exception as e:
            raise Exception(f"Error applying configuration: {str(e)}")

        return changes

    def _update_repo_settings(self, repo, config: Dict[str, Any], changes: Dict[str, Any]) -> None:
        """Update repository settings"""
        current_settings = {
            "name": repo.name,
            "visibility": "private" if repo.private else "internal",
            "has_issues": repo.has_issues,
            "has_wiki": repo.has_wiki,
            "has_projects": repo.has_projects,
            "default_branch": repo.default_branch,
        }

        new_settings = {}
        for key, value in config.items():
            if key in current_settings and current_settings[key] != value:
                new_settings[key] = value

        if new_settings:
            repo.edit(**new_settings)
            changes["settings"] = new_settings

    def _update_branch_protection(self, repo, rulesets: List[Dict[str, Any]], changes: Dict[str, Any]) -> None:
        """Update branch protection rules"""
        # Implementation for updating branch protection rules
        pass

    def _update_custom_properties(self, repo, properties: List[Dict[str, Any]], changes: Dict[str, Any]) -> None:
        """Update custom properties"""
        # Implementation for updating custom properties
        pass

    def _comment_on_issue(self, issue, message: str) -> None:
        """Add comment to issue"""
        issue.create_comment(message)
