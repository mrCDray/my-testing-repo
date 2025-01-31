import os
import re
import yaml
import sys
import json
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.StreamHandler(sys.stdout),
                        logging.FileHandler('repo_creation_debug.log')
                    ])

from github import Github, GithubException

def get_github_context():
    """
    Retrieve GitHub context from environment variables and event payload
    """
    # Get environment variables
    github_token = os.environ.get('GITHUB_TOKEN')
    github_event_path = os.environ.get('GITHUB_EVENT_PATH')
    
    logging.debug(f"GITHUB_TOKEN present: {bool(github_token)}")
    logging.debug(f"GITHUB_EVENT_PATH: {github_event_path}")
    
    # Parse GitHub event payload
    event_payload = {}
    if github_event_path and os.path.exists(github_event_path):
        try:
            with open(github_event_path, 'r') as event_file:
                event_payload = json.load(event_file)
            logging.debug("Event payload successfully parsed")
        except Exception as e:
            logging.error(f"Error parsing event payload: {e}")
    
    # Extract context information
    context = {
        'token': github_token,
        'repository': os.environ.get('GITHUB_REPOSITORY', ''),
        'event_name': os.environ.get('GITHUB_EVENT_NAME', ''),
        'ref': os.environ.get('GITHUB_REF', ''),
        'actor': os.environ.get('GITHUB_ACTOR', ''),
        'issue_number': None,
        'organization': None
    }
    
    # Extract issue number from payload or environment
    if 'issue' in event_payload:
        context['issue_number'] = event_payload['issue'].get('number')
    
    # Extract organization from repository name
    if context['repository']:
        context['organization'] = context['repository'].split('/')[0]
    
    # Logging all extracted context
    logging.debug("GitHub Context:")
    for key, value in context.items():
        logging.debug(f"{key}: {value}")
    
    return context, event_payload

class RepositoryCreationHandler:
    def __init__(self, github_token, org_name):
        """
        Initialize the Repository Creation Handler
        
        :param github_token: GitHub Personal Access Token
        :param org_name: GitHub Organization Name
        """
        self.g = Github(github_token)
        self.org = self.g.get_organization(org_name)
        self.org_name = org_name
    
    def process_issue(self, issue, event_payload):
        """
        Process repository creation issue
        
        :param issue: GitHub Issue object
        :param event_payload: Event payload dictionary
        """
        logging.info(f"Processing issue #{issue.number}")
        
        # Parse issue body
        input_data = self.parse_issue_body(issue.body)
        
        # Validate inputs
        validation_results = {
            'name': self.validate_repository_name(input_data.get('repo-name', '')),
            'description': self.validate_description(input_data.get('description', ''))
        }
        
        # Log validation results
        logging.debug("Validation Results:")
        for key, (is_valid, message) in validation_results.items():
            logging.debug(f"{key}: Valid={is_valid}, Message={message}")
        
        # Check if all validations passed
        if all(result[0] for result in validation_results.values()):
            # Generate and create repository
            config = self.generate_repository_config(input_data)
            repo = self.create_repository(config)
            
            if repo:
                # Success comment
                success_comment = f"""
## 🎉 Repository Created Successfully!

Repository **{repo.full_name}** created:
- Name: {repo.name}
- Description: {repo.description}
- Visibility: {'Private' if repo.private else 'Public'}

Configuration: `.github/repo_settings.yml`

[View Repository]({repo.html_url})
"""
                issue.create_comment(success_comment)
                issue.edit(state='closed')
                logging.info(f"Repository {repo.name} created successfully")
            else:
                # Creation failed
                issue.create_comment("❌ **Repository Creation Failed**\nContact administrator.")
                logging.error("Repository creation failed")
        else:
            # Validation failed
            feedback_comment = self.generate_validation_comment(validation_results)
            issue.create_comment(feedback_comment)
            logging.warning("Repository creation validation failed")
    
    def parse_issue_body(self, body):
        """
        Parse issue body into input dictionary
        """
        input_data = {}
        current_section = None
        
        for line in body.split('\n'):
            line = line.strip()
            
            # Handle section headers
            if line.startswith('### '):
                current_section = line[4:].lower().replace(' ', '_')
                continue
            
            # Parse key-value pairs
            if ':' in line and current_section:
                key, value = line.split(':', 1)
                input_data[current_section] = value.strip()
        
        logging.debug(f"Parsed Input Data: {input_data}")
        return input_data
    
    # ... [previous validation and config generation methods remain the same]

def main():
    # Get GitHub context and event payload
    context, event_payload = get_github_context()
    
    # Validate required context
    if not context['token']:
        logging.error("GitHub token not found")
        sys.exit(1)
    
    if not context['organization']:
        logging.error("Organization could not be determined")
        sys.exit(1)
    
    # Initialize GitHub instance
    g = Github(context['token'])
    
    try:
        # Determine repository containing issues
        org_repos = list(g.get_organization(context['organization']).get_repos())
        logging.debug(f"Organization repositories: {[repo.name for repo in org_repos]}")
        
        # Try to find the .github repository
        github_repo = next((repo for repo in org_repos if repo.name == '.github'), None)
        
        if not github_repo:
            logging.error("No .github repository found in the organization")
            sys.exit(1)
        
        # Retrieve issue
        if context['issue_number']:
            issue = github_repo.get_issue(context['issue_number'])
            
            # Process the issue
            handler = RepositoryCreationHandler(context['token'], context['organization'])
            handler.process_issue(issue, event_payload)
        else:
            logging.error("No issue number found in the event payload")
            sys.exit(1)
    
    except Exception as e:
        logging.error(f"Error processing repository creation: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()