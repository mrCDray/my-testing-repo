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
        with open('default_repository.yml', 'r') as f:
            return yaml.safe_load(f)

    def parse_issue_body(self, body: str) -> Dict[str, Any]:
        """Parse issue body to extract configuration parameters"""
        config = {}
        sections = re.split(r'^### ', body, flags=re.MULTILINE)[1:]
        
        for section in sections:
            lines = section.strip().split('\n')
            if not lines:
                continue
                
            section_name = lines[0].lower().replace(' ', '_')
            section_content = '\n'.join(lines[1:]).strip()
            
            if section_content.startswith('```yaml'):
                # Parse YAML content
                yaml_content = section_content.replace('```yaml', '').replace('```', '').strip()
                try:
                    config[section_name] = yaml.safe_load(yaml_content)
                except yaml.YAMLError as e:
                    raise ValueError(f"Invalid YAML in {section_name}: {str(e)}")
            else:
                # Parse key-value pairs
                config[section_name] = {}
                for line in section_content.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        config[section_name][key.strip()] = value.strip()
        
        return config

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate repository configuration against allowed values"""
        errors = []
        
        # Basic validation rules
        if 'repository' in config:
            repo_config = config['repository']
            
            # Validate visibility
            if 'visibility' in repo_config:
                if repo_config['visibility'] not in ['internal', 'private']:
                    errors.append("Visibility must be either 'internal' or 'private'")
            
            # Validate branch name
            if 'default_branch' in repo_config:
                if not re.match(r'^[a-zA-Z0-9_-]+$', repo_config['default_branch']):
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
            issue.edit(state='closed')
            
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
            repo = self.org.get_repo(config['repository']['name'])
            
            # Apply updates
            changes = self._apply_repository_config(repo, config)
            
            # Close issue with success message
            self._comment_on_issue(issue, f"Repository {repo.name} updated successfully:\n{yaml.dump(changes)}")
            issue.edit(state='closed')
            
        except Exception as e:
            self._comment_on_issue(issue, f"Error processing repository update: {str(e)}")

    def _create_repository(self, config: Dict[str, Any]):
        """Create new repository with basic settings"""
        repo_config = config['repository']
        return self.org.create_repo(
            name=repo_config['name'],
            private=(repo_config['visibility'] == 'private'),
            internal=(repo_config['visibility'] == 'internal'),
            auto_init=True
        )

    def _apply_repository_config(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply configuration to repository and return changes made"""
        changes = {}
        
        try:
            # Apply repository settings
            repo_config = config.get('repository', {})
            self._update_repo_settings(repo, repo_config, changes)
            
            # Apply branch protection
            if 'rulesets' in config:
                self._update_branch_protection(repo, config['rulesets'], changes)
            
            # Apply custom properties
            if 'custom_properties' in config:
                self._update_custom_properties(repo, config['custom_properties'], changes)
                
        except Exception as e:
            raise Exception(f"Error applying configuration: {str(e)}")
            
        return changes

    def _update_repo_settings(self, repo, config: Dict[str, Any], changes: Dict[str, Any]) -> None:
        """Update repository settings"""
        current_settings = {
            'name': repo.name,
            'visibility': 'private' if repo.private else 'internal',
            'has_issues': repo.has_issues,
            'has_wiki': repo.has_wiki,
            'has_projects': repo.has_projects,
            'default_branch': repo.default_branch
        }
        
        new_settings = {}
        for key, value in config.items():
            if key in current_settings and current_settings[key] != value:
                new_settings[key] = value
                
        if new_settings:
            repo.edit(**new_settings)
            changes['settings'] = new_settings

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