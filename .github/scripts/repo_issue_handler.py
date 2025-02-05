import re
import yaml
import logging
from typing import Dict, Any, Optional, Tuple, List
from github import Github, GithubException
from repo_sync_manager import RepoSyncManager


class RepoIssueHandler:
    def __init__(self, token: str, org_name: str):
        self.github = Github(token)
        self.org = self.github.get_organization(org_name)
        self.sync_manager = RepoSyncManager(token, org_name)
        self.logger = logging.getLogger(__name__)

    def process_issue(self, issue_number: int, repo_name: str) -> None:
        """Process repository creation/update issue"""
        try:
            # Get the issue from the repository
            repo = self.org.get_repo(repo_name)
            issue = repo.get_issue(issue_number)

            # Parse and validate the issue body
            config, validation_errors = self._parse_and_validate_issue(issue)

            if validation_errors:
                self._handle_validation_errors(issue, validation_errors)
                return

            # Check if repository exists
            repo_exists = self._check_repository_exists(config["repository"]["name"])

            try:
                if repo_exists:
                    self._handle_update(issue, config)
                else:
                    self._handle_creation(issue, config)
            except Exception as e:
                self._handle_error(issue, str(e))

        except Exception as e:
            self.logger.error(f"Error processing issue {issue_number}: {str(e)}")
            raise

    def _parse_and_validate_issue(self, issue) -> Tuple[Dict[str, Any], List[str]]:
        """Parse issue body and validate configuration"""
        errors = []
        config = {}

        try:
            config = self._parse_issue_body(issue)
            is_valid, validation_errors = self._validate_config(config)
            if not is_valid:
                errors.extend(validation_errors)
        except Exception as e:
            errors.append(f"Error parsing issue: {str(e)}")

        return config, errors

    def _parse_issue_body(self, issue) -> Dict[str, Any]:
        """Parse issue body with improved form field extraction"""
        form_data = issue.body
        config = {}

        # Define field mappings
        field_mappings = {
            "repository": {"name": "repo-name", "visibility": "visibility", "description": "description"},
            "template": "temp-repo-name",
        }

        # Extract basic fields
        for section, fields in field_mappings.items():
            if isinstance(fields, dict):
                config[section] = {}
                for config_key, form_key in fields.items():
                    value = self._extract_form_field(form_data, form_key)
                    if value:
                        config[section][config_key] = value
            else:
                value = self._extract_form_field(form_data, fields)
                if value:
                    config[section] = value

        # Extract and parse YAML sections
        yaml_sections = ["repo-config", "security-settings", "branch-protection", "custom-properties"]

        for section in yaml_sections:
            yaml_content = self._extract_yaml_section(form_data, section)
            if yaml_content:
                try:
                    parsed_yaml = yaml.safe_load(yaml_content)
                    self._merge_configs(config, parsed_yaml)
                except yaml.YAMLError as e:
                    self.logger.error(f"Error parsing YAML in {section}: {str(e)}")
                    raise ValueError(f"Invalid YAML in {section}: {str(e)}")

        return config

    def _extract_form_field(self, form_data: str, field_id: str) -> Optional[str]:
        """Extract value from form field with improved parsing"""
        patterns = [
            f"### {field_id}\\s*\\n\\s*([^#\\n]+)",  # Basic field
            f"### {field_id}\\s*\\n\\s*```[^\\n]*\\n(.+?)```",  # Code block
            f"### {field_id}\\s*\\n\\s*- \\[[ x]\\] (.+)",  # Checkbox
        ]

        for pattern in patterns:
            match = re.search(pattern, form_data, re.DOTALL | re.MULTILINE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_yaml_section(self, form_data: str, section_id: str) -> Optional[str]:
        """Extract YAML content from form section"""
        pattern = f"### {section_id}\\s*\\n\\s*```ya?ml\\s*\\n(.+?)```"
        match = re.search(pattern, form_data, re.DOTALL | re.MULTILINE)
        return match.group(1) if match else None

    def _merge_configs(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Merge configurations recursively"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target:
                if not isinstance(target[key], dict):
                    target[key] = {}
                self._merge_configs(target[key], value)
            elif value is not None:
                target[key] = value

    def _validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate repository configuration"""
        errors = []

        # Required fields
        if "repository" not in config:
            errors.append("Missing repository configuration section")
        else:
            repo_config = config["repository"]

            # Validate repository name
            if "name" not in repo_config:
                errors.append("Repository name is required")
            elif not re.match(r"^[a-zA-Z0-9_.-]+$", repo_config["name"]):
                errors.append("Invalid repository name format")

            # Validate visibility
            if "visibility" in repo_config:
                if repo_config["visibility"] not in ["internal", "private"]:
                    errors.append("Visibility must be either 'internal' or 'private'")

        # Validate YAML sections
        if "rulesets" in config:
            if not isinstance(config["rulesets"], list):
                errors.append("Rulesets must be a list")

        if "custom_properties" in config:
            if not isinstance(config["custom_properties"], list):
                errors.append("Custom properties must be a list")

        return len(errors) == 0, errors

    def _check_repository_exists(self, repo_name: str) -> bool:
        """Check if repository exists"""
        try:
            self.org.get_repo(repo_name)
            return True
        except GithubException:
            return False

    def _handle_creation(self, issue, config: Dict[str, Any]) -> None:
        """Handle repository creation"""
        try:
            repo_name = config["repository"]["name"]
            template_repo = config.get("template")

            self.sync_manager.create_repository(repo_name=repo_name, config=config, template_repo_name=template_repo)

            success_msg = (
                f"✅ Repository {repo_name} created successfully!\n\n"
                f"Repository URL: https://github.com/{self.org.login}/{repo_name}\n\n"
                "The following configurations have been applied:\n"
                f"```yaml\n{yaml.dump(config, default_flow_style=False)}\n```"
            )

            self._close_issue_with_success(issue, success_msg)

        except Exception as e:
            error_msg = (
                f"❌ Failed to create repository: {str(e)}\n\n"
                "Please check the following:\n"
                "- Repository name is valid and available\n"
                "- Template repository exists (if specified)\n"
                "- All configuration values are valid"
            )
            self._handle_error(issue, error_msg)

    def _handle_update(self, issue, config: Dict[str, Any]) -> None:
        """Handle repository update"""
        try:
            repo_name = config["repository"]["name"]
            changes = self.sync_manager.update_repository(repo_name, config)

            if changes:
                success_msg = (
                    f"✅ Repository {repo_name} updated successfully!\n\n"
                    "The following changes were applied:\n"
                    f"```yaml\n{yaml.dump(changes, default_flow_style=False)}\n```"
                )
            else:
                success_msg = f"ℹ️ Repository {repo_name} is already up to date.\n" "No changes were necessary."

            self._close_issue_with_success(issue, success_msg)

        except Exception as e:
            error_msg = (
                f"❌ Failed to update repository: {str(e)}\n\n"
                "Please check the following:\n"
                "- All configuration values are valid\n"
                "- You have necessary permissions\n"
                "- The repository exists and is accessible"
            )
            self._handle_error(issue, error_msg)

    def _handle_validation_errors(self, issue, errors: List[str]) -> None:
        """Handle validation errors"""
        error_msg = "❌ Invalid repository configuration\n\n" "Please fix the following issues:\n"
        for error in errors:
            error_msg += f"- {error}\n"

        error_msg += "\nPlease update the issue with the correct configuration and try again."
        self._comment_on_issue(issue, error_msg)
        self._add_label_to_issue(issue, "invalid-config")

    def _handle_error(self, issue, error_msg: str) -> None:
        """Handle general errors"""
        self._comment_on_issue(issue, error_msg)
        self._add_label_to_issue(issue, "failed")

    def _close_issue_with_success(self, issue, message: str) -> None:
        """Close issue with success message"""
        self._comment_on_issue(issue, message)
        self._add_label_to_issue(issue, "completed")
        issue.edit(state="closed")

    def _comment_on_issue(self, issue, message: str) -> None:
        """Add comment to issue"""
        try:
            issue.create_comment(message)
        except Exception as e:
            self.logger.error(f"Error commenting on issue: {str(e)}")

    def _add_label_to_issue(self, issue, label: str) -> None:
        """Add label to issue"""
        try:
            issue.add_to_labels(label)
        except Exception as e:
            self.logger.error(f"Error adding label to issue: {str(e)}")
