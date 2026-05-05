"""User Story Enricher for TODO output.

Enriches feature_user_story_map.toml with AI-generated User Story details.
This is Phase 1 of the post-processing enrichment pipeline.

KEY PRINCIPLE:
    Reads DIRECTLY from feature_user_story_map.toml (the source of truth).
    Does NOT parse TODO markdown.
    Uses source_location from TOML to access source files.
    Writes enriched descriptions to Odoo task descriptions (HTML format).
    Does NOT write descriptions to TOML - only complexity/time are written to TOML.

Usage:
    python -m shared.python.user_story_enricher project_root -o enriched_todo.md
"""

import argparse
import logging
import re
import shutil
import sys
import tomllib
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .ai_providers import AIProvider, AIProviderError, get_provider
    from .enricher_config import EnricherConfig, UserStoryEnricherConfig
    from .odoo_client import OdooClient, OdooClientError
except ImportError:
    from ai_providers import AIProvider, AIProviderError, get_provider
    from enricher_config import EnricherConfig, UserStoryEnricherConfig
    from odoo_client import OdooClient, OdooClientError


logger = logging.getLogger(__name__)


# Common Odoo model to domain mapping for context
MODEL_DOMAIN_MAP = {
    "sale.order": "Sales",
    "sale.order.line": "Sales",
    "purchase.order": "Purchasing",
    "purchase.order.line": "Purchasing",
    "stock.picking": "Inventory",
    "stock.move": "Inventory",
    "stock.quant": "Inventory",
    "account.move": "Accounting",
    "account.move.line": "Accounting",
    "account.payment": "Accounting",
    "res.partner": "Contacts",
    "res.users": "Users & Access",
    "res.company": "Settings",
    "product.product": "Products",
    "product.template": "Products",
    "mrp.production": "Manufacturing",
    "mrp.bom": "Manufacturing",
    "project.project": "Projects",
    "project.task": "Projects",
    "hr.employee": "HR",
    "hr.leave": "HR",
    "crm.lead": "CRM",
}

# Common role mapping by domain
DOMAIN_ROLES = {
    "Sales": ["Sales Representative", "Sales Manager", "Account Manager"],
    "Purchasing": ["Procurement Specialist", "Purchasing Manager", "Buyer"],
    "Inventory": ["Warehouse Operator", "Inventory Manager", "Logistics Coordinator"],
    "Accounting": ["Accountant", "Financial Controller", "Billing Specialist"],
    "Contacts": ["Sales Representative", "Customer Service Rep", "Administrator"],
    "Products": ["Product Manager", "Inventory Manager", "Sales Representative"],
    "Manufacturing": ["Production Manager", "Shop Floor Operator", "Planner"],
    "Projects": ["Project Manager", "Team Member", "Resource Manager"],
    "HR": ["HR Manager", "Employee", "Recruiter"],
    "CRM": ["Sales Representative", "Marketing Manager", "Account Executive"],
}


@dataclass
class TomlComponent:
    """A component from feature_user_story_map.toml."""
    
    ref: str
    source_location: str | None = None
    component_type: str = ""
    model: str = ""
    name: str = ""
    source_content: str | None = None  # Loaded from source_location
    complexity: str | None = None  # Complexity level (simple, medium, complex)
    time_estimate: str | None = None  # Time estimate (e.g., "1:30")
    completion: str | None = None  # Completion percentage (e.g., "50%")
    
    @classmethod
    def from_toml_item(cls, item: dict | str, project_root: Path) -> "TomlComponent":
        """Create from TOML component item (string or dict with ref/source_location)."""
        if isinstance(item, dict):
            ref = item.get("ref", "")
            source_location = item.get("source_location")
            complexity = item.get("complexity")
            time_estimate = item.get("time_estimate")
            completion = item.get("completion")
        else:
            ref = str(item)
            source_location = None
            complexity = None
            time_estimate = None
            completion = None
        
        # Parse ref: type.model.name format
        parts = ref.split(".", 2)
        if len(parts) >= 3:
            comp_type = parts[0]
            model = parts[1].replace("_", ".")
            name = parts[2]
        elif len(parts) == 2:
            comp_type = parts[0]
            model = "unknown"
            name = parts[1]
        else:
            comp_type = "unknown"
            model = "unknown"
            name = ref
        
        # Load source content if source_location exists
        source_content = None
        if source_location:
            source_path = project_root / source_location
            if source_path.exists() and source_path.is_file():
                try:
                    source_content = source_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Failed to read source file {source_path}: {e}")
        
        return cls(
            ref=ref,
            source_location=source_location,
            component_type=comp_type,
            model=model,
            name=name,
            source_content=source_content,
            complexity=complexity,
            time_estimate=time_estimate,
            completion=completion,
        )


@dataclass
class TomlUserStory:
    """A user story from feature_user_story_map.toml."""
    
    name: str  # The user story name (key in TOML)
    description: str  # The description (property in TOML)
    sequence: int
    components: list[TomlComponent]
    enrich_status: str = "refresh-all"  # Control enrichment operations
    task_id: int = 0  # External task tracker ID
    tags: str = "Story"  # Categorization tags
    
    # AI-enriched fields (to be added)
    role: str | None = None
    goal: str | None = None
    benefit: str | None = None
    acceptance_criteria: list[str] = field(default_factory=list)
    ai_enriched: bool = False


@dataclass
class TomlFeature:
    """A feature from feature_user_story_map.toml."""
    
    name: str
    description: str
    sequence: int
    user_stories: list[TomlUserStory]
    enrich_status: str = "refresh-all"  # Control enrichment operations
    task_id: int = 0  # External task tracker ID
    tags: str = "Feature"  # Categorization tags
    
    # AI-enriched fields (to be added)
    goal: str | None = None
    ai_enriched: bool = False
    
    @property
    def primary_model(self) -> str:
        """Get the primary model (most common) in the feature."""
        models = []
        for story in self.user_stories:
            for comp in story.components:
                if comp.model and comp.model != "unknown":
                    models.append(comp.model)
        if not models:
            return "unknown"
        return max(set(models), key=models.count)
    
    @property
    def domain(self) -> str:
        """Get the domain based on primary model."""
        return MODEL_DOMAIN_MAP.get(self.primary_model, "General")


class TomlLoader:
    """Load features directly from feature_user_story_map.toml."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.studio_dir = project_root / "studio"
        self.map_file = self.studio_dir / "feature_user_story_map.toml"
    
    def load_features(self) -> list[TomlFeature]:
        """Load all features from TOML.
        
        Supports both new dict-based user_stories format and legacy list format.
        
        Returns:
            List of TomlFeature objects with components
        """
        if not self.map_file.exists():
            raise ValueError(f"feature_user_story_map.toml not found: {self.map_file}")
        
        with open(self.map_file, "rb") as f:
            data = tomllib.load(f)
        
        features_data = data.get("features", {})
        features = []
        
        for feature_name, feature_def in features_data.items():
            # Skip deprecated features
            if feature_def.get("_deprecated"):
                continue
            
            user_stories = []
            user_stories_data = feature_def.get("user_stories", {})
            
            # Handle both dict format (new) and list format (legacy)
            if isinstance(user_stories_data, dict):
                # New format: user_stories is a dict with story name as key
                for story_name, story_data in user_stories_data.items():
                    components = [
                        TomlComponent.from_toml_item(item, self.project_root)
                        for item in story_data.get("components", [])
                    ]
                    
                    user_stories.append(TomlUserStory(
                        name=story_name,
                        description=story_data.get("description", ""),
                        sequence=story_data.get("sequence", 999),
                        enrich_status=story_data.get("enrich-status", "refresh-all"),
                        task_id=story_data.get("task_id", 0),
                        tags=story_data.get("tags", "Story"),
                        components=components,
                    ))
            else:
                # Legacy format: user_stories is a list
                for story_data in user_stories_data:
                    components = [
                        TomlComponent.from_toml_item(item, self.project_root)
                        for item in story_data.get("components", [])
                    ]
                    
                    # Get story name - use 'name' field or fall back to description
                    story_name = story_data.get("name", story_data.get("description", "Unnamed User Story"))
                    user_stories.append(TomlUserStory(
                        name=story_name,
                        description=story_data.get("description", ""),
                        sequence=story_data.get("sequence", 999),
                        enrich_status=story_data.get("enrich-status", "refresh-all"),
                        task_id=story_data.get("task_id", 0),
                        tags=story_data.get("tags", "Story"),
                        components=components,
                    ))
            
            features.append(TomlFeature(
                name=feature_name,
                description=feature_def.get("description", feature_name),
                sequence=feature_def.get("sequence", 999),
                enrich_status=feature_def.get("enrich-status", "refresh-all"),
                task_id=feature_def.get("task_id", 0),
                tags=feature_def.get("tags", "Feature"),
                user_stories=user_stories,
            ))
        
        # Sort by sequence
        features.sort(key=lambda f: (f.sequence, f.name))
        return features


class UserStoryGenerator:
    """Generate enriched user stories using AI."""
    
    SYSTEM_PROMPT = """You are an expert Odoo business analyst. Your task is to analyze 
Odoo Studio customizations and generate user story details that explain the business value.

You have deep knowledge of:
- Odoo ERP modules (Sales, Purchasing, Inventory, Accounting, etc.)
- Business processes and workflows
- User roles in enterprise software
- Acceptance criteria best practices

Output format requirements:
- Use clear, business-focused language
- Each user story should follow: As a [Role], I want [Goal], so that [Benefit]
- Acceptance criteria should be testable and specific
- Infer the business domain from model names and field types"""

    def __init__(
        self, 
        provider: AIProvider,
        config: UserStoryEnricherConfig
    ):
        self.provider = provider
        self.config = config
    
    def enrich_feature(self, feature: TomlFeature) -> TomlFeature:
        """Enrich a feature with AI-generated goal and user story details.
        
        Args:
            feature: TomlFeature to enrich
            
        Returns:
            Enriched TomlFeature
        """
        prompt = self._build_prompt(feature)
        
        try:
            response = self.provider.generate(prompt, self.SYSTEM_PROMPT)
            return self._parse_response(response.content, feature)
        except AIProviderError as e:
            logger.warning(f"AI generation failed for {feature.name}: {e}")
            return self._create_fallback(feature)
    
    def _build_prompt(self, feature: TomlFeature) -> str:
        """Build the AI prompt for a feature.
        
        Generates prompts that produce enriched descriptions only.
        No new fields are created - all content goes into existing description fields.
        The user story NAME is never changed - only the description is enriched.
        """
        domain = feature.domain
        roles = DOMAIN_ROLES.get(domain, ["User", "Manager", "Administrator"])
        
        # Build component details with source code snippets
        component_details = []
        for story in feature.user_stories:
            # Use story.name as the identifier (never change it)
            component_details.append(f"\n### User Story: {story.name}")
            for comp in story.components:
                details = f"- {comp.name} ({comp.component_type}) on {comp.model}"
                if comp.source_content:
                    # Include first 50 lines of source for context
                    lines = comp.source_content.split('\n')[:50]
                    snippet = '\n'.join(lines)
                    details += f"\n  ```\n{snippet}\n  ```"
                component_details.append(details)
        
        # Build list of user story names (not descriptions) for the prompt
        story_names = [s.name for s in feature.user_stories]
        
        prompt = f"""Analyze the following Odoo Studio customizations and generate enriched descriptions.

## Feature: {feature.name}

**Current Description:** {feature.description}
**Primary Model:** {feature.primary_model}
**Domain:** {domain}
**Common Roles:** {', '.join(roles)}

### Components and User Stories:
{chr(10).join(component_details)}

---

Generate output in this EXACT format:

**Feature Description:** [A single paragraph describing the business value and purpose of this feature. Be concise but comprehensive.]

### User Story: {story_names[0] if story_names else 'User Story 1'}

**Description:**
- 👤 Who: [The specific persona/role who will use this]
- 🎯 What: [The specific action, capability, or feature they need]
- 💡 Why: [The business value or problem this solves]
- ✅ How (Acceptance Criteria):
  - [Criterion 1 - specific, testable, and measurable]
  - [Criterion 2 - specific, testable, and measurable]
  - [Criterion 3 - specific, testable, and measurable]

(Repeat for each user story: {', '.join(story_names)})

❌ WRONG FORMAT (DO NOT USE):
**Description:**
- 👤 Who: Warehouse Operator - 🎯 What: Track packaging - 💡 Why: accuracy - ✅ How: criteria here

✅ CORRECT FORMAT (USE THIS EXACTLY):
**Description:**
- 👤 Who: Warehouse Operator
- 🎯 What: Track packaging status for all products in a stock transfer
- 💡 Why: To ensure customer orders are fulfilled accurately and prevent shipping errors
- ✅ How (Acceptance Criteria):
  - System displays packaging status (packaged/not packaged) for each product line
  - Stock transfer cannot be validated until all products show "packaged" status
  - User can view packaging instructions and package count per product
  - "Pack as Per Order" button creates required packages automatically

MANDATORY FORMATTING RULES:
1. NEWLINE after "- 👤 Who: [text]" - next bullet on NEW LINE
2. NEWLINE after "- 🎯 What: [text]" - next bullet on NEW LINE  
3. NEWLINE after "- 💡 Why: [text]" - next bullet on NEW LINE
4. NEWLINE after "- ✅ How (Acceptance Criteria):" - sub-bullets on NEW LINES
5. NO combining multiple sections on one line with dashes between them
6. Each icon (👤 🎯 💡 ✅) must start a NEW bullet point
7. Sub-criteria under "How" must be indented with "  - " (two spaces + dash)
8. Do NOT change the user story names - only provide descriptions"""

        return prompt
    
    def _parse_response(self, response: str, feature: TomlFeature) -> TomlFeature:
        """Parse AI response and enrich the feature.
        
        Updates the description fields only - names are NEVER modified.
        """
        # Extract feature description
        feat_desc_match = re.search(r'\*\*Feature Description:\*\*\s*(.+?)(?=\n###|$)', response, re.DOTALL)
        if feat_desc_match:
            feature.description = feat_desc_match.group(1).strip()
        feature.ai_enriched = True
        
        # Parse user story descriptions
        # Pattern matches: ### User Story: <name>\n**Description:** <content>
        story_pattern = re.compile(
            r'###\s+User Story:\s*(.+?)\n.*?\*\*Description:\*\*\s*(.+?)(?=\n###|$)',
            re.DOTALL | re.IGNORECASE
        )
        
        parsed_stories = {}
        for match in story_pattern.finditer(response):
            story_name = match.group(1).strip()
            description = match.group(2).strip()
            # Clean up the description - normalize whitespace but preserve structure
            description = re.sub(r'\n\s*-', '\n-', description)  # Normalize list items
            parsed_stories[story_name] = description
        
        # Match parsed stories to feature's user stories by NAME (not description)
        for story in feature.user_stories:
            # Try exact match first on name, then partial
            new_description = parsed_stories.get(story.name)
            if not new_description:
                for parsed_name, desc in parsed_stories.items():
                    if story.name.lower() in parsed_name.lower() or parsed_name.lower() in story.name.lower():
                        new_description = desc
                        break
            
            if new_description:
                # Only update description, NEVER change the name
                story.description = new_description
                story.ai_enriched = True
            else:
                # Fallback for unmatched stories
                self._apply_fallback_story(story, feature)
        
        return feature
    
    def _apply_fallback_story(self, story: TomlUserStory, feature: TomlFeature) -> None:
        """Apply fallback enrichment to a user story.
        
        Creates a structured description when AI parsing fails.
        The story NAME is never changed - only description is updated.
        """
        domain = feature.domain
        role = DOMAIN_ROLES.get(domain, ["User"])[0]
        
        # Build a structured description using the story name
        story.description = (
            f"- Who: {role}\n"
            f"- What: {story.name}\n"
            f"- Why: To complete workflow efficiently\n"
            f"- How (Acceptance Criteria):\n"
            f"  - All component(s) are implemented\n"
            f"  - The feature integrates with existing workflows"
        )
        story.ai_enriched = True
        
        # Keep legacy fields for backward compatibility but don't use them
        story.role = role
        story.goal = f"use the {story.name.lower()}"
        story.benefit = "I can complete my workflow efficiently"
        story.acceptance_criteria = [
            f"All {len(story.components)} component(s) are implemented",
            "The feature integrates with existing workflows",
        ]
    
    def _create_fallback(self, feature: TomlFeature) -> TomlFeature:
        """Create fallback enrichment when AI fails."""
        feature.goal = f"Implement customizations for {feature.primary_model}"
        feature.ai_enriched = False
        
        for story in feature.user_stories:
            self._apply_fallback_story(story, feature)
        
        return feature


class MarkdownGenerator:
    """Generate enriched TODO markdown from features."""
    
    def __init__(self, config: UserStoryEnricherConfig):
        self.config = config
    
    def generate(self, features: list[TomlFeature], project_name: str = "Project") -> str:
        """Generate enriched TODO markdown.
        
        Args:
            features: List of enriched TomlFeature objects
            project_name: Name for the project header
            
        Returns:
            Complete TODO markdown content
        """
        lines = [
            f"# {project_name} - Implementation TODO",
            "",
            f"*Generated with AI enrichment*",
            "",
        ]
        
        if self.config.mark_ai_generated:
            lines.extend([
                "> **Note:** User stories were enriched using AI.",
                "> Please review and adjust as needed.",
                "",
            ])
        
        # Summary statistics
        total_stories = sum(len(f.user_stories) for f in features)
        total_components = sum(
            len(c.components) for f in features for c in f.user_stories
        )
        
        lines.extend([
            "## Summary",
            "",
            f"- **Features:** {len(features)}",
            f"- **User Stories:** {total_stories}",
            f"- **Components:** {total_components}",
            "",
            "---",
            "",
        ])
        
        # Render each feature
        for feature in features:
            lines.extend(self._render_feature(feature))
            lines.append("")
        
        return "\n".join(lines)
    
    def _render_feature(self, feature: TomlFeature) -> list[str]:
        """Render a single feature as markdown."""
        lines = [
            f"## Feature: {feature.name}",
            "",
        ]
        
        if feature.goal:
            lines.append(f"**Goal:** {feature.goal}")
            lines.append("")
        
        if feature.ai_enriched and self.config.mark_ai_generated:
            lines.append("*[AI-Enriched]*")
            lines.append("")
        
        # Render user stories
        for i, story in enumerate(feature.user_stories, 1):
            lines.extend(self._render_user_story(story, i))
            lines.append("")
        
        return lines
    
    def _render_user_story(self, story: TomlUserStory, index: int) -> list[str]:
        """Render a single user story as markdown.
        
        Uses story.name as the title (preserved) and story.description for content.
        """
        lines = [
            f"### User Story {index}: {story.name}",
            "",
        ]
        
        # Include the enriched description
        if story.description:
            lines.append(story.description)
            lines.append("")
        
        if story.role and story.goal and story.benefit:
            lines.append(
                f"* **Story:** As a **{story.role}**, I want to {story.goal}, "
                f"so that {story.benefit}."
            )
        
        if story.acceptance_criteria:
            lines.append("* **Acceptance Criteria:**")
            for criterion in story.acceptance_criteria:
                lines.append(f"  * {criterion}")
        
        # List components
        if story.components:
            lines.append("")
            lines.append("**Components:**")
            for comp in story.components:
                source_info = ""
                if comp.source_location:
                    source_info = f" → `{comp.source_location}`"
                lines.append(f"- `{comp.ref}`{source_info}")
        
        return lines


class OdooHtmlGenerator:
    """Generate Odoo-compatible HTML descriptions for task descriptions.
    
    Generates formatted HTML that renders properly in Odoo task descriptions,
    using inline CSS for styling compatibility with Odoo's web client.
    """
    
    # Error HTML for failed enrichment
    ERROR_HTML = '''<div style="background-color: #ffebee; border: 2px solid #c62828; border-radius: 8px; padding: 20px; margin: 10px 0; text-align: center;">
    <p style="color: #c62828; font-size: 24px; font-weight: bold; margin: 0;">⚠️ ENRICHMENT FAILED</p>
    <p style="color: #666; margin-top: 10px;">Please re-run enrichment or check the logs for details.</p>
</div>'''
    
    # CSS styles as constants for consistency
    # Color Palette: Dark Teal (#003339), Rusty Spice (#af2e00), Muted Teal (#899e8b), Muted Teal 2 (#99c5b5), Icy Aqua (#afece7)
    STYLES = {
        'header': 'color: #003339; border-bottom: 2px solid #af2e00; padding-bottom: 8px; margin-bottom: 16px;',
        'subheader': 'color: #003339; margin-top: 20px; margin-bottom: 12px;',
        'blockquote': 'background-color: #99c5b5; border-left: 4px solid #af2e00; padding: 15px 20px; margin: 15px 0; border-radius: 0 8px 8px 0;',
        'feature_ref': 'color: #003339; font-style: italic; margin-bottom: 15px;',
        'table': 'width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px;',
        'th': 'background-color: #003339; color: white; padding: 12px 15px; text-align: left; font-weight: 600;',
        'td': 'padding: 10px 15px; border-bottom: 1px solid #899e8b;',
        'td_status': 'padding: 10px 15px; border-bottom: 1px solid #899e8b; text-align: center; width: 60px;',
        'tr_hover': 'background-color: #99c5b5;',
        'tr_total': 'background-color: #899e8b; font-weight: bold;',
        'label': 'color: #af2e00; font-weight: 600;',
        'criteria_list': 'margin: 10px 0 0 0; padding-left: 20px;',
        'criteria_item': 'margin: 5px 0; color: #003339;',
        'badge_simple': 'background-color: #afece7; color: #003339; padding: 2px 8px; border-radius: 4px; font-size: 12px;',
        'badge_medium': 'background-color: #af2e00; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;',
        'badge_complex': 'background-color: #003339; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;',
        'badge_unknown': 'background-color: #899e8b; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;',
    }
    
    @classmethod
    def _get_complexity_badge(cls, complexity: str) -> str:
        """Get styled complexity badge HTML."""
        complexity_lower = str(complexity).lower()
        if complexity_lower == 'simple':
            style = cls.STYLES['badge_simple']
        elif complexity_lower == 'medium':
            style = cls.STYLES['badge_medium']
        elif complexity_lower in ('complex', 'high'):
            style = cls.STYLES['badge_complex']
        else:
            style = cls.STYLES['badge_unknown']
        return f'<span style="{style}">{cls._escape_html(str(complexity))}</span>'
    
    @classmethod
    def generate_feature_html(
        cls,
        feature: "TomlFeature",
        include_user_stories_table: bool = True,
        timesheet_data: dict[int, float] | None = None,
    ) -> str:
        """Generate HTML for a feature task description.
        
        Args:
            feature: TomlFeature object with enriched data
            include_user_stories_table: Whether to include user stories summary table
            timesheet_data: Dict mapping task_id to actual hours (optional)
            
        Returns:
            Formatted HTML string for Odoo task description
        """
        html_parts = []
        
        # Feature header with icon
        html_parts.append(f'<h2 style="{cls.STYLES["header"]}">📋 {cls._escape_html(feature.name)}</h2>')
        
        # Business requirement / description in styled blockquote
        if feature.description:
            html_parts.append(f'<div style="{cls.STYLES["blockquote"]}">')
            html_parts.append(f'<p style="margin: 0 0 10px 0;"><strong style="{cls.STYLES["label"]}">Business Requirement</strong></p>')
            html_parts.append(f'<p style="margin: 0; color: #2c3e50; line-height: 1.6;">{cls._escape_html(feature.description)}</p>')
            html_parts.append('</div>')
        
        # User stories summary table
        if include_user_stories_table and feature.user_stories:
            html_parts.append(f'<h3 style="{cls.STYLES["subheader"]}">📝 User Stories</h3>')
            html_parts.append(cls._generate_stories_table(
                feature.user_stories,
                timesheet_data=timesheet_data,
                feature_task_id=feature.task_id if hasattr(feature, 'task_id') else 0,
            ))
        
        return '\n'.join(html_parts)
    
    @classmethod
    def generate_user_story_html(
        cls,
        story: "TomlUserStory",
        feature_name: str = "",
        timesheet_data: dict[int, float] | None = None,
    ) -> str:
        """Generate HTML for a user story task description.
        
        Args:
            story: TomlUserStory object with enriched data
            feature_name: Parent feature name for context
            timesheet_data: Dict mapping task_id to actual hours (optional)
            
        Returns:
            Formatted HTML string for Odoo task description
        """
        html_parts = []
        
        # User story header
        html_parts.append(f'<h2 style="{cls.STYLES["header"]}">📋 {cls._escape_html(story.name)}</h2>')
        
        # Parent feature reference
        if feature_name:
            html_parts.append(f'<p style="{cls.STYLES["feature_ref"]}">🔗 Feature: {cls._escape_html(feature_name)}</p>')
        
        # Business requirement block with structured description
        html_parts.append(f'<div style="{cls.STYLES["blockquote"]}">')
        html_parts.append(f'<p style="margin: 0 0 10px 0;"><strong style="{cls.STYLES["label"]}">Business Requirement</strong></p>')
        
        # Parse the structured description if it contains Who/What/Why/How (with or without emojis)
        description = story.description or ""
        if any(marker in description for marker in ["Who:", "What:", "Why:", "How", "👤", "🎯", "💡", "✅"]):
            html_parts.append(cls._format_structured_description(description))
        else:
            # Plain description
            html_parts.append(f'<p style="margin: 0; color: #2c3e50; line-height: 1.6;">{cls._escape_html(description)}</p>')
        
        html_parts.append('</div>')
        
        # Components table
        if story.components:
            html_parts.append(f'<h3 style="{cls.STYLES["subheader"]}">⚙️ Components</h3>')
            html_parts.append(cls._generate_components_table(
                story.components,
                timesheet_data=timesheet_data,
                story_task_id=story.task_id if hasattr(story, 'task_id') else 0,
            ))
        
        return '\n'.join(html_parts)
    
    @classmethod
    def _format_structured_description(cls, description: str) -> str:
        """Format a structured Who/What/Why/How description as HTML.
        
        Args:
            description: Description text with Who/What/Why/How markers
            
        Returns:
            Formatted HTML
        """
        lines = []
        
        # Parse the description for structured fields
        # Support both plain format (Who:) and emoji format (👤 Who:)
        who_match = re.search(r'-?\s*(?:👤\s*)?Who[:\s]+(.+?)(?=\n-?\s*(?:🎯\s*)?What|\n-?\s*(?:💡\s*)?Why|\n-?\s*(?:✅\s*)?How|$)', description, re.IGNORECASE | re.DOTALL)
        what_match = re.search(r'-?\s*(?:🎯\s*)?What[:\s]+(.+?)(?=\n-?\s*(?:👤\s*)?Who|\n-?\s*(?:💡\s*)?Why|\n-?\s*(?:✅\s*)?How|$)', description, re.IGNORECASE | re.DOTALL)
        why_match = re.search(r'-?\s*(?:💡\s*)?Why[:\s]+(.+?)(?=\n-?\s*(?:👤\s*)?Who|\n-?\s*(?:🎯\s*)?What|\n-?\s*(?:✅\s*)?How|$)', description, re.IGNORECASE | re.DOTALL)
        how_match = re.search(r'-?\s*(?:✅\s*)?How[^:]*[:\s]+(.+?)$', description, re.IGNORECASE | re.DOTALL)
        
        if who_match:
            lines.append(f'<p style="margin: 8px 0;"><strong style="{cls.STYLES["label"]}">👤 Who:</strong> {cls._escape_html(who_match.group(1).strip())}</p>')
        
        if what_match:
            lines.append(f'<p style="margin: 8px 0;"><strong style="{cls.STYLES["label"]}">🎯 What:</strong> {cls._escape_html(what_match.group(1).strip())}</p>')
        
        if why_match:
            lines.append(f'<p style="margin: 8px 0;"><strong style="{cls.STYLES["label"]}">💡 Why:</strong> {cls._escape_html(why_match.group(1).strip())}</p>')
        
        if how_match:
            how_content = how_match.group(1).strip()
            lines.append(f'<p style="margin: 12px 0 8px 0;"><strong style="{cls.STYLES["label"]}">✅ Acceptance Criteria:</strong></p>')
            
            # Parse acceptance criteria as list items
            criteria = re.findall(r'-\s*(.+?)(?=\n\s*-|\Z)', how_content, re.DOTALL)
            if criteria:
                lines.append(f'<ul style="{cls.STYLES["criteria_list"]}">')
                for criterion in criteria:
                    criterion_text = criterion.strip()
                    if criterion_text:
                        lines.append(f'<li style="{cls.STYLES["criteria_item"]}">{cls._escape_html(criterion_text)}</li>')
                lines.append('</ul>')
            else:
                lines.append(f'<p style="margin: 0; color: #2c3e50;">{cls._escape_html(how_content)}</p>')
        
        return '\n'.join(lines) if lines else f'<p style="margin: 0; color: #2c3e50; line-height: 1.6;">{cls._escape_html(description)}</p>'
    
    @classmethod
    def _generate_stories_table(
        cls,
        stories: list["TomlUserStory"],
        timesheet_data: dict[int, float] | None = None,
        feature_task_id: int = 0,
    ) -> str:
        """Generate HTML table for user stories summary.
        
        Args:
            stories: List of TomlUserStory objects
            timesheet_data: Dict mapping task_id to actual hours (optional)
            feature_task_id: Feature task ID for feature-level time row (optional)
            
        Returns:
            HTML table string
        """
        rows = []
        total_estimate_hours = 0.0
        total_actual_hours = 0.0
        
        for story in stories:
            # Calculate total estimate hours for this story
            story_estimate_hours = 0.0
            for comp in story.components:
                if hasattr(comp, 'time_estimate') and comp.time_estimate:
                    try:
                        time_str = str(comp.time_estimate)
                        parts = time_str.split(":")
                        story_estimate_hours += float(parts[0]) + float(parts[1]) / 60
                    except (ValueError, IndexError, AttributeError):
                        pass
            
            total_estimate_hours += story_estimate_hours
            estimate_int = int(story_estimate_hours)
            estimate_minutes = int((story_estimate_hours - estimate_int) * 60)
            estimate_display = f"{estimate_int:02d}:{estimate_minutes:02d}"
            
            # Get actual hours from timesheet data
            story_actual_hours = 0.0
            actual_display = "00:00"
            if timesheet_data and story.task_id and story.task_id > 0:
                story_actual_hours = timesheet_data.get(story.task_id, 0.0)
                total_actual_hours += story_actual_hours
                actual_int = int(story_actual_hours)
                actual_minutes = int((story_actual_hours - actual_int) * 60)
                actual_display = f"{actual_int:02d}:{actual_minutes:02d}"
            
            # Get average complexity
            complexities = [getattr(c, 'complexity', 'unknown') for c in story.components if hasattr(c, 'complexity')]
            complexity = complexities[0] if complexities else "unknown"
            complexity_badge = cls._get_complexity_badge(complexity)
            
            # Status indicator
            status = "⏳"  # Default pending
            
            rows.append(f'''<tr style="border-bottom: 1px solid #ecf0f1;">
      <td style="{cls.STYLES['td_status']}">{status}</td>
      <td style="{cls.STYLES['td']}">{cls._escape_html(story.name)}</td>
      <td style="{cls.STYLES['td']}; text-align: center;">{complexity_badge}</td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;">{estimate_display}</td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;">{actual_display}</td>
    </tr>''')
        
        # Add "Time at feature level" row before Total (if feature_task_id is provided)
        if feature_task_id > 0 and timesheet_data:
            feature_actual_hours = timesheet_data.get(feature_task_id, 0.0)
            total_actual_hours += feature_actual_hours  # Add to total actual
            feature_actual_int = int(feature_actual_hours)
            feature_actual_minutes = int((feature_actual_hours - feature_actual_int) * 60)
            feature_actual_display = f"{feature_actual_int:02d}:{feature_actual_minutes:02d}"
            
            rows.append(f'''<tr style="border-bottom: 1px solid #ecf0f1;">
      <td style="{cls.STYLES['td_status']}"></td>
      <td style="{cls.STYLES['td']}">Time at feature level</td>
      <td style="{cls.STYLES['td']}"></td>
      <td style="{cls.STYLES['td']}"></td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;">{feature_actual_display}</td>
    </tr>''')
        
        # Total row (includes feature-level time in actual total)
        total_estimate_int = int(total_estimate_hours)
        total_estimate_minutes = int((total_estimate_hours - total_estimate_int) * 60)
        total_estimate_display = f"{total_estimate_int:02d}:{total_estimate_minutes:02d}"
        
        total_actual_int = int(total_actual_hours)
        total_actual_minutes = int((total_actual_hours - total_actual_int) * 60)
        total_actual_display = f"{total_actual_int:02d}:{total_actual_minutes:02d}"
        
        rows.append(f'''<tr style="{cls.STYLES['tr_total']}">
      <td style="{cls.STYLES['td_status']}"></td>
      <td style="{cls.STYLES['td']}"><strong>Total</strong></td>
      <td style="{cls.STYLES['td']}"></td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;"><strong>{total_estimate_display}</strong></td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;"><strong>{total_actual_display}</strong></td>
    </tr>''')
        
        return f'''<table style="{cls.STYLES['table']}">
  <thead>
    <tr>
      <th style="{cls.STYLES['th']}; text-align: center; width: 60px;">Status</th>
      <th style="{cls.STYLES['th']}">Name</th>
      <th style="{cls.STYLES['th']}; text-align: center; width: 100px;">Complexity</th>
      <th style="{cls.STYLES['th']}; text-align: right; width: 80px;">Estimate</th>
      <th style="{cls.STYLES['th']}; text-align: right; width: 80px;">Actual</th>
    </tr>
  </thead>
  <tbody>
    {chr(10).join(rows)}
  </tbody>
</table>'''
    
    @classmethod
    def _generate_components_table(
        cls,
        components: list["TomlComponent"],
        timesheet_data: dict[int, float] | None = None,
        story_task_id: int = 0,
    ) -> str:
        """Generate HTML table for components.
        
        Args:
            components: List of TomlComponent objects
            timesheet_data: Dict mapping task_id to actual hours (optional)
            story_task_id: Story task ID for fetching actual hours (optional)
            
        Returns:
            HTML table string
        """
        rows = []
        total_estimate_hours = 0.0
        
        for comp in components:
            # Get component details - handle both object and dict formats
            # Use 'or' to handle None values (getattr/get return None if attr exists but is None)
            if isinstance(comp, dict):
                name = comp.get('ref') or comp.get('name') or 'Unknown'
                complexity = comp.get('complexity') or 'unknown'
                time_estimate = comp.get('time_estimate') or '0:00'
                completion = comp.get('completion') or '0%'
            else:
                name = getattr(comp, 'ref', None) or getattr(comp, 'name', None) or 'Unknown'
                complexity = getattr(comp, 'complexity', None) or 'unknown'
                time_estimate = getattr(comp, 'time_estimate', None) or '0:00'
                completion = getattr(comp, 'completion', None) or '0%'
            
            # Parse time
            try:
                time_str = str(time_estimate)
                parts = time_str.split(":")
                hours = float(parts[0]) + float(parts[1]) / 60
                total_estimate_hours += hours
            except (ValueError, IndexError):
                hours = 0.0
            
            # Status indicator based on completion
            if completion == "100%":
                status = "✅"
            elif completion == "0%":
                status = "⏳"
            else:
                status = "🔄"
            
            complexity_badge = cls._get_complexity_badge(complexity)
            
            # Format component name nicely
            display_name = str(name)
            if '.' in display_name:
                # Split ref like "field.sale_order.x_test" into readable format
                parts = display_name.split('.', 2)
                if len(parts) >= 3:
                    display_name = f'<code style="background-color: #ecf0f1; padding: 2px 6px; border-radius: 3px; font-size: 12px;">{parts[0]}</code> {parts[2]}'
            
            rows.append(f'''<tr style="border-bottom: 1px solid #ecf0f1;">
      <td style="{cls.STYLES['td_status']}">{status}</td>
      <td style="{cls.STYLES['td']}">{display_name}</td>
      <td style="{cls.STYLES['td']}; text-align: center;">{complexity_badge}</td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;">{time_estimate}</td>
    </tr>''')
        
        # Total Estimate row
        total_estimate_int = int(total_estimate_hours)
        total_estimate_minutes = int((total_estimate_hours - total_estimate_int) * 60)
        total_estimate_display = f"{total_estimate_int:02d}:{total_estimate_minutes:02d}"
        
        rows.append(f'''<tr style="{cls.STYLES['tr_total']}">
      <td style="{cls.STYLES['td_status']}"></td>
      <td style="{cls.STYLES['td']}"><strong>Total Estimate</strong></td>
      <td style="{cls.STYLES['td']}"></td>
      <td style="{cls.STYLES['td']}; text-align: right; font-family: monospace;"><strong>{total_estimate_display}</strong></td>
    </tr>''')
        
        # Total Actual row (using header style)
        total_actual_hours = 0.0
        if timesheet_data and story_task_id and story_task_id > 0:
            total_actual_hours = timesheet_data.get(story_task_id, 0.0)
        
        total_actual_int = int(total_actual_hours)
        total_actual_minutes = int((total_actual_hours - total_actual_int) * 60)
        total_actual_display = f"{total_actual_int:02d}:{total_actual_minutes:02d}"
        
        rows.append(f'''<tr>
      <th style="{cls.STYLES['th']}; text-align: center;"></th>
      <th style="{cls.STYLES['th']}">Total Actual</th>
      <th style="{cls.STYLES['th']}; text-align: center;"></th>
      <th style="{cls.STYLES['th']}; text-align: right; font-family: monospace;">{total_actual_display}</th>
    </tr>''')
        
        return f'''<table style="{cls.STYLES['table']}">
  <thead>
    <tr>
      <th style="{cls.STYLES['th']}; text-align: center; width: 60px;">Status</th>
      <th style="{cls.STYLES['th']}">Component</th>
      <th style="{cls.STYLES['th']}; text-align: center; width: 100px;">Complexity</th>
      <th style="{cls.STYLES['th']}; text-align: right; width: 80px;">Estimate</th>
    </tr>
  </thead>
  <tbody>
    {chr(10).join(rows)}
  </tbody>
</table>'''
    
    @classmethod
    def _escape_html(cls, text: str) -> str:
        """Escape HTML special characters.
        
        Args:
            text: Text to escape
            
        Returns:
            HTML-escaped text
        """
        if not text:
            return ""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )


class UserStoryEnricher:
    """Main class for enriching TODO output with user stories.
    
    Reads directly from feature_user_story_map.toml and uses source_location
    to access source files for AI context.
    """
    
    def __init__(
        self,
        config: EnricherConfig | None = None,
        provider: AIProvider | None = None,
    ):
        """Initialize the enricher.
        
        Args:
            config: Enricher configuration (uses defaults if not provided)
            provider: AI provider (creates one from config if not provided)
        """
        self.config = config or EnricherConfig.default()
        self.use_config = self.config.user_story_enricher
        
        if provider:
            self.provider = provider
        else:
            self.provider = get_provider(
                self.use_config.ai_provider,
                model=self.use_config.model,
                temperature=self.use_config.temperature,
            )
        
        self.generator_ai = UserStoryGenerator(self.provider, self.use_config)
        self.markdown_gen = MarkdownGenerator(self.use_config)
    
    def enrich(
        self,
        project_root: Path,
        dry_run: bool = False,
    ) -> str:
        """Enrich features from TOML with AI-generated user stories.
        
        Args:
            project_root: Path to project root (contains studio/ folder)
            dry_run: If True, show what would be generated without AI calls
            
        Returns:
            Enriched markdown content
        """
        # Load features directly from TOML
        loader = TomlLoader(project_root)
        features = loader.load_features()
        
        if not features:
            logger.warning("No features found in feature_user_story_map.toml")
            return "# No features found\n"
        
        logger.info(f"Loaded {len(features)} features from TOML")
        
        if dry_run:
            return self._generate_dry_run_output(features)
        
        # Enrich each feature with AI
        enriched_features = []
        for feature in features:
            logger.info(f"Enriching feature: {feature.name}")
            enriched = self.generator_ai.enrich_feature(feature)
            enriched_features.append(enriched)
        
        # Generate markdown output
        project_name = project_root.name
        return self.markdown_gen.generate(enriched_features, project_name)
    
    def _generate_dry_run_output(self, features: list[TomlFeature]) -> str:
        """Generate a preview of what would be enriched."""
        lines = [
            "# Dry Run Preview",
            "",
            "The following features would be enriched:",
            "",
        ]
        
        for feature in features:
            lines.extend([
                f"## Feature: {feature.name}",
                f"- Primary Model: {feature.primary_model}",
                f"- Domain: {feature.domain}",
                f"- User Stories: {len(feature.user_stories)}",
            ])
            
            for story in feature.user_stories:
                # Show story name (which is preserved) and current description
                lines.append(f"  - {story.name} ({len(story.components)} components)")
                if story.description:
                    lines.append(f"    Current description: {story.description[:50]}...")
                for comp in story.components:
                    has_source = "✓ has source" if comp.source_location else "✗ no source"
                    lines.append(f"    - {comp.ref} [{has_source}]")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def enrich_and_save(
        self,
        project_root: Path,
        output_path: Path | None = None,
        **kwargs
    ) -> str:
        """DEPRECATED: Use enrich_in_place() instead.
        
        This method is deprecated and will be removed in a future version.
        Use enrich_in_place() which updates the TOML file directly and
        uses the updated TOML as the source of truth.
        
        Args:
            project_root: Path to project root
            output_path: Ignored (kept for backward compatibility)
            **kwargs: Additional arguments
            
        Returns:
            dict with enrichment results
        """
        import warnings
        warnings.warn(
            "enrich_and_save() is deprecated. Use enrich_in_place() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        # Redirect to the new in-place enrichment
        return self.enrich_in_place(project_root, **kwargs)

    def _write_toml_file(self, path: Path, data: dict) -> None:
        """Write TOML data to file.
        
        Reuses the TOML writing logic from FeatureUserStoryMapGenerator._write_toml()
        
        Args:
            path: Path to write TOML file
            data: TOML data dictionary
        """
        try:
            from .feature_user_story_map_generator import FeatureUserStoryMapGenerator
        except ImportError:
            from feature_user_story_map_generator import FeatureUserStoryMapGenerator
        
        generator = FeatureUserStoryMapGenerator(path.parent.parent, verbose=False)
        generator._write_toml(data)

    # REMOVED: _regenerate_todo() method
    # The feature_user_story_map.toml is the primary source for user stories.

    def enrich_stories_in_place(
        self,
        project_root: Path,
        dry_run: bool = False,
        odoo_client: OdooClient | None = None,
    ) -> dict:
        """Enriches features/stories with AI and writes HTML descriptions to Odoo.
        
        This method:
        1. Generates AI-enriched descriptions for features and user stories
        2. Writes HTML-formatted descriptions to Odoo task descriptions
        3. Updates enrich-status in TOML (but NOT descriptions)
        4. Keeps backup of TOML for safety
        
        Descriptions are written ONLY to Odoo, NOT to TOML.
        Complexity/time estimation is done separately via estimate_effort_in_place().
        
        Does NOT generate additional output files.
        
        Args:
            project_root: Root directory of the project
            dry_run: If True, verify connections only, don't enrich or write
            odoo_client: OdooClient for writing to Odoo (required for non-dry-run)
        
        Returns:
            dict with keys:
                - backup_toml: Path to backed up feature_user_story_map.toml  
                - features_enriched: int count
                - user_stories_enriched: int count
                - odoo_tasks_updated: int count
                - errors: list of error messages
        """
        # 1. Validate files exist
        map_file = project_root / "studio" / "feature_user_story_map.toml"
        
        if not map_file.exists():
            raise FileNotFoundError(f"Map file not found: {map_file}")
        
        # 2. Dry run: verify AI connection only
        if dry_run:
            logger.info("🔍 Dry run mode: Verifying AI connection...")
            try:
                # Just verify provider is initialized
                _ = self.provider
                logger.info("✓ AI connection verified")
            except Exception as e:
                raise RuntimeError(f"AI connection failed: {e}")
            
            # Count what would be enriched
            loader = TomlLoader(project_root)
            features = loader.load_features()
            total_stories = sum(len(f.user_stories) for f in features)
            
            return {
                "features_enriched": len(features),
                "user_stories_enriched": total_stories,
                "odoo_tasks_updated": 0,
                "errors": [],
            }
        
        # 3. Validate Odoo client for non-dry-run
        if odoo_client is None:
            raise ValueError("OdooClient is required for non-dry-run enrichment")
        
        # 4. Create backup
        from utils import create_timestamped_backup
        backup_toml = create_timestamped_backup(map_file, keep=5)
        if backup_toml:
            logger.info(f"Created backup: {backup_toml.name}")
        
        # 5. Load TOML
        loader = TomlLoader(project_root)
        features = loader.load_features()
        
        # Load raw TOML data for writing status updates back
        with open(map_file, "rb") as f:
            toml_data = tomllib.load(f)
        
        # 6. Fetch timesheet data for all tasks
        print("\nFetching timesheet data from Odoo...")
        timesheet_data: dict[int, float] = {}
        for feature in features:
            if feature.task_id and feature.task_id > 0:
                try:
                    timesheet_data[feature.task_id] = odoo_client.fetch_task_timesheets(feature.task_id)
                except Exception as e:
                    logger.warning(f"Failed to fetch timesheets for feature task {feature.task_id}: {e}")
                    timesheet_data[feature.task_id] = 0.0
            
            for story in feature.user_stories:
                if story.task_id and story.task_id > 0:
                    try:
                        timesheet_data[story.task_id] = odoo_client.fetch_task_timesheets(story.task_id)
                    except Exception as e:
                        logger.warning(f"Failed to fetch timesheets for story task {story.task_id}: {e}")
                        timesheet_data[story.task_id] = 0.0
        
        print(f"✓ Fetched timesheet data for {len(timesheet_data)} tasks")
        
        # 7. Enrich descriptions with AI and write to Odoo
        features_enriched = 0
        user_stories_enriched = 0
        odoo_tasks_updated = 0
        errors = []
        
        for feature in features:
            feature_name = feature.name
            feature_task_id = feature.task_id
            feature_enrich_status = feature.enrich_status
            print(f"\nProcessing feature: {feature_name} (status: {feature_enrich_status}, task_id: {feature_task_id})")
            
            # Check if feature-level enrichment should run
            # IMPORTANT: Feature and story enrichment are INDEPENDENT
            should_enrich_feature = feature_enrich_status in ["refresh-all", "refresh-stories"]
            
            # Check if ANY story in this feature needs enrichment
            user_stories_toml = toml_data["features"][feature_name].get("user_stories", {})
            any_story_needs_enrichment = False
            
            if isinstance(user_stories_toml, dict):
                for story_data in user_stories_toml.values():
                    story_enrich_status = story_data.get("enrich-status", "refresh-all")
                    if story_enrich_status in ["refresh-all", "refresh-stories"]:
                        any_story_needs_enrichment = True
                        break
            else:
                for story_data in user_stories_toml:
                    story_enrich_status = story_data.get("enrich-status", "refresh-all")
                    if story_enrich_status in ["refresh-all", "refresh-stories"]:
                        any_story_needs_enrichment = True
                        break
            
            # Skip entire feature only if NEITHER feature nor any story needs enrichment
            if not should_enrich_feature and not any_story_needs_enrichment:
                print(f"  → Feature and all stories: skipped (no enrichment needed)")
                continue
            
            try:
                # Call AI enrichment logic (needed for both feature and story enrichment)
                enriched_feature = self.generator_ai.enrich_feature(feature)
                
                # Process feature enrichment (only if feature needs it)
                if should_enrich_feature:
                    features_enriched += 1
                    
                    # Generate HTML for feature and write to Odoo
                    if feature_task_id > 0:
                        try:
                            feature_html = OdooHtmlGenerator.generate_feature_html(
                                enriched_feature,
                                timesheet_data=timesheet_data,
                            )
                            odoo_client.write(
                                "project.task",
                                [feature_task_id],
                                {"description": feature_html}
                            )
                            odoo_tasks_updated += 1
                            print(f"  → Feature description: written to Odoo task #{feature_task_id}")
                        except OdooClientError as e:
                            # Write error message to Odoo task
                            try:
                                odoo_client.write(
                                    "project.task",
                                    [feature_task_id],
                                    {"description": OdooHtmlGenerator.ERROR_HTML}
                                )
                            except OdooClientError:
                                pass  # Best effort
                            error_msg = f"Failed to write feature '{feature_name}' to Odoo: {e}"
                            errors.append(error_msg)
                            logger.error(error_msg)
                            print(f"  ✗ {error_msg}")
                    else:
                        print(f"  → Feature: no task_id, skipping Odoo write")
                    
                    # Update feature enrich-status in TOML
                    # If was refresh-all, transition to refresh-effort (stories done, effort still needed)
                    # If was refresh-stories, transition to done (no effort estimation needed)
                    if feature_enrich_status == "refresh-all":
                        toml_data["features"][feature_name]["enrich-status"] = "refresh-effort"
                    else:  # refresh-stories
                        toml_data["features"][feature_name]["enrich-status"] = "done"
                else:
                    print(f"  → Feature: skipped (status={feature_enrich_status})")
                
                # Process user stories INDEPENDENTLY of feature status
                # Handle both dict format (new) and list format (legacy)
                if isinstance(user_stories_toml, dict):
                    # New format: user_stories is a dict with story name as key
                    for enriched_story in enriched_feature.user_stories:
                        story_name = enriched_story.name
                        if story_name not in user_stories_toml:
                            continue
                        
                        story_data = user_stories_toml[story_name]
                        story_task_id = story_data.get("task_id", 0)
                        story_enrich_status = story_data.get("enrich-status", "refresh-all")
                        should_enrich_story = story_enrich_status in ["refresh-all", "refresh-stories"]
                        
                        if not should_enrich_story:
                            print(f"  → User Story '{story_name}': skipped (status={story_enrich_status})")
                            continue
                        
                        if enriched_story.ai_enriched:
                            user_stories_enriched += 1
                            
                            # Write HTML to Odoo
                            if story_task_id > 0:
                                try:
                                    story_html = OdooHtmlGenerator.generate_user_story_html(
                                        enriched_story,
                                        feature_name,
                                        timesheet_data=timesheet_data,
                                    )
                                    odoo_client.write(
                                        "project.task",
                                        [story_task_id],
                                        {"description": story_html}
                                    )
                                    odoo_tasks_updated += 1
                                    print(f"  → User Story '{story_name}': written to Odoo task #{story_task_id}")
                                except OdooClientError as e:
                                    # Write error message to Odoo task
                                    try:
                                        odoo_client.write(
                                            "project.task",
                                            [story_task_id],
                                            {"description": OdooHtmlGenerator.ERROR_HTML}
                                        )
                                    except OdooClientError:
                                        pass  # Best effort
                                    error_msg = f"Failed to write story '{story_name}' to Odoo: {e}"
                                    errors.append(error_msg)
                                    logger.error(error_msg)
                                    print(f"  ✗ {error_msg}")
                            else:
                                print(f"  → User Story '{story_name}': no task_id, skipping Odoo write")
                            
                            # Update story enrich-status in TOML
                            # If was refresh-all, transition to refresh-effort (stories done, effort still needed)
                            # If was refresh-stories, transition to done (no effort estimation needed)
                            if story_enrich_status == "refresh-all":
                                user_stories_toml[story_name]["enrich-status"] = "refresh-effort"
                            else:  # refresh-stories
                                user_stories_toml[story_name]["enrich-status"] = "done"
                else:
                    # Legacy list format
                    for i, enriched_story in enumerate(enriched_feature.user_stories):
                        if i >= len(user_stories_toml):
                            continue
                        
                        story_data = user_stories_toml[i]
                        story_task_id = story_data.get("task_id", 0)
                        story_enrich_status = story_data.get("enrich-status", "refresh-all")
                        should_enrich_story = story_enrich_status in ["refresh-all", "refresh-stories"]
                        
                        if not should_enrich_story:
                            print(f"  → User Story {i + 1}: skipped (status={story_enrich_status})")
                            continue
                        
                        if enriched_story.ai_enriched:
                            user_stories_enriched += 1
                            
                            # Write HTML to Odoo
                            if story_task_id > 0:
                                try:
                                    story_html = OdooHtmlGenerator.generate_user_story_html(
                                        enriched_story,
                                        feature_name,
                                        timesheet_data=timesheet_data,
                                    )
                                    odoo_client.write(
                                        "project.task",
                                        [story_task_id],
                                        {"description": story_html}
                                    )
                                    odoo_tasks_updated += 1
                                    print(f"  → User Story {i + 1}: written to Odoo task #{story_task_id}")
                                except OdooClientError as e:
                                    # Write error message to Odoo task
                                    try:
                                        odoo_client.write(
                                            "project.task",
                                            [story_task_id],
                                            {"description": OdooHtmlGenerator.ERROR_HTML}
                                        )
                                    except OdooClientError:
                                        pass  # Best effort
                                    error_msg = f"Failed to write story {i + 1} to Odoo: {e}"
                                    errors.append(error_msg)
                                    logger.error(error_msg)
                                    print(f"  ✗ {error_msg}")
                            else:
                                print(f"  → User Story {i + 1}: no task_id, skipping Odoo write")
                            
                            # Update story enrich-status in TOML
                            # If was refresh-all, transition to refresh-effort (stories done, effort still needed)
                            # If was refresh-stories, transition to done (no effort estimation needed)
                            if story_enrich_status == "refresh-all":
                                user_stories_toml[i]["enrich-status"] = "refresh-effort"
                            else:  # refresh-stories
                                user_stories_toml[i]["enrich-status"] = "done"
            
            except Exception as e:
                error_msg = f"Enrichment failed for {feature_name}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)
                continue
        
        # 7. Write updated TOML (only enrich-status changes, NOT descriptions)
        self._write_toml_file(map_file, toml_data)
        logger.info(f"Updated TOML enrich-status: {map_file}")
        
        return {
            "backup_toml": backup_toml,
            "features_enriched": features_enriched,
            "user_stories_enriched": user_stories_enriched,
            "odoo_tasks_updated": odoo_tasks_updated,
            "errors": errors,
        }

    def estimate_effort_in_place(
        self,
        project_root: Path,
        dry_run: bool = False,
    ) -> dict:
        """Updates TOML in-place with complexity and time estimates.
        
        This method ONLY does complexity/time estimation. For AI enrichment of
        descriptions, use enrich_stories_in_place().
        
        Note: feature_user_story_map.toml is the primary source for user stories.
        
        Respects enrich-status field:
        - "refresh-all" or "refresh-effort": Estimation runs
        - "refresh-stories": Estimation skipped
        - "done": Estimation skipped
        
        Args:
            project_root: Root directory of the project
            dry_run: If True, preview only, don't write
        
        Returns:
            dict with keys:
                - backup_toml: Path to backed up feature_user_story_map.toml  
                - components_enriched: int count
                - total_hours: float total hours
                - errors: list of error messages
        """
        # Import needed modules
        try:
            from .complexity_analyzer import ComplexityAnalyzer, resolve_source_location
            from .effort_estimator import TimeMetrics
        except ImportError:
            from complexity_analyzer import ComplexityAnalyzer, resolve_source_location
            from effort_estimator import TimeMetrics
        
        # 1. Validate files exist
        map_file = project_root / "studio" / "feature_user_story_map.toml"
        
        if not map_file.exists():
            raise FileNotFoundError(f"Map file not found: {map_file}")
        
        # Load raw TOML data
        with open(map_file, "rb") as f:
            toml_data = tomllib.load(f)
        
        # Get time_factor from statistics section (default to 1.0 if not present)
        time_factor = toml_data.get("statistics", {}).get("time_factor", 1.0)
        logger.info(f"Using time_factor: {time_factor}")
        
        # 2. Dry run: count what would be estimated
        if dry_run:
            logger.info("🔍 Dry run mode: Counting components...")
            total_components = 0
            for feature_def in toml_data.get("features", {}).values():
                user_stories = feature_def.get("user_stories", {})
                # Handle both dict format (new) and list format (legacy)
                if isinstance(user_stories, dict):
                    for story_data in user_stories.values():
                        total_components += len(story_data.get("components", []))
                else:
                    for story in user_stories:
                        total_components += len(story.get("components", []))
            
            return {
                "components_enriched": total_components,
                "total_hours": 0.0,
                "errors": [],
            }
        
        # 3. Create backup
        from utils import create_timestamped_backup
        backup_toml = create_timestamped_backup(map_file, keep=5)
        if backup_toml:
            logger.info(f"Created backup: {backup_toml.name}")
        
        # 4. Process components
        # Load time metrics from project config - REQUIRED
        time_metrics_path = project_root / ".odoo-sync" / "config" / "time_metrics.json"
        if not time_metrics_path.exists():
            # Try templates directory
            time_metrics_path = project_root / "templates" / "time_metrics.json"
        
        if not time_metrics_path.exists():
            raise FileNotFoundError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: time_metrics.json not found!\n"
                f"{'='*60}\n"
                f"Searched locations:\n"
                f"  - {project_root / '.odoo-sync' / 'config' / 'time_metrics.json'}\n"
                f"  - {project_root / 'templates' / 'time_metrics.json'}\n\n"
                f"This file is REQUIRED for effort estimation.\n"
                f"{'='*60}\n"
            )
        
        logger.info(f"Loading time metrics from: {time_metrics_path}")
        time_metrics = TimeMetrics.from_file(time_metrics_path)
        # Create analyzer with component-type-specific complexity rules
        complexity_analyzer = ComplexityAnalyzer.from_config_file(time_metrics_path)
        
        components_enriched = 0
        total_hours = 0.0
        errors = []
        
        for feature_name, feature_def in toml_data["features"].items():
            feature_enrich_status = feature_def.get("enrich-status", "refresh-all")
            print(f"\nAnalyzing components for: {feature_name} (status: {feature_enrich_status})")
            
            # Check if feature-level effort estimation should run
            # IMPORTANT: Feature and story estimation are INDEPENDENT
            should_estimate_feature = feature_enrich_status in ["refresh-all", "refresh-effort"]
            
            user_stories = feature_def.get("user_stories", {})
            # Handle both dict format (new) and list format (legacy)
            if isinstance(user_stories, dict):
                story_items = list(user_stories.items())
            else:
                # Legacy list format - create named items
                story_items = [(f"Story {i+1}", story) for i, story in enumerate(user_stories)]
            
            # Check if ANY story in this feature needs effort estimation
            any_story_needs_estimation = False
            for story_name, story_data in story_items:
                story_enrich_status = story_data.get("enrich-status", "refresh-all")
                if story_enrich_status in ["refresh-all", "refresh-effort"]:
                    any_story_needs_estimation = True
                    break
            
            # Skip entire feature only if NEITHER feature nor any story needs estimation
            if not should_estimate_feature and not any_story_needs_estimation:
                print(f"  → Feature and all stories: skipped (no estimation needed)")
                continue
            
            feature_had_any_work = False
            
            for story_name, story_data in story_items:
                story_enrich_status = story_data.get("enrich-status", "refresh-all")
                print(f"  → User Story: {story_name} (status: {story_enrich_status})")
                
                # Check if story-level effort estimation should run
                # Stories are processed INDEPENDENTLY of feature status
                should_estimate_story = story_enrich_status in ["refresh-all", "refresh-effort"]
                
                if not should_estimate_story:
                    print(f"    → Skipped (status={story_enrich_status})")
                    continue
                
                components = story_data.get("components", [])
                story_enriched_any = False
                
                for i, comp_item in enumerate(components):
                    # Normalize to dict format (backward compatibility)
                    if isinstance(comp_item, str):
                        comp_dict = {
                            "ref": comp_item,
                            "source_location": False,
                            "complexity": "unknown",
                            "time_estimate": "0:00",
                            "completion": "100%",
                        }
                        components[i] = comp_dict
                    else:
                        comp_dict = comp_item
                    
                    print(f"    → Component: {comp_dict.get('ref', 'unknown')}")
                    
                    # Skip if already enriched UNLESS enrich-status says to re-trigger
                    # When refresh-all or refresh-effort is set, always re-estimate
                    is_enriched = (
                        comp_dict.get("complexity", "unknown") != "unknown" and
                        comp_dict.get("time_estimate", "0:00") != "0:00"
                    )
                    should_skip = is_enriched and not should_estimate_story
                    
                    if should_skip:
                        print(f"      ↳ Skipping (already estimated, use enrich-status to re-trigger)")
                        # Still count existing hours
                        existing_time = comp_dict.get("time_estimate", "0:00")
                        try:
                            parts = existing_time.split(":")
                            total_hours += float(parts[0]) + float(parts[1]) / 60
                        except (ValueError, IndexError):
                            pass
                        continue
                    
                    try:
                        comp = TomlComponent.from_toml_item(comp_dict, project_root)
                        
                        # Extract component type from ref (e.g., "field.x_name" -> "field")
                        ref_parts = comp.ref.split(".")
                        comp_type = ref_parts[0] if len(ref_parts) > 0 else "unknown"
                        
                        # For field components, extract the field name to analyze just that field
                        field_name = None
                        if comp_type == "field" and len(ref_parts) >= 3:
                            field_name = ref_parts[-1]  # Last part is field name
                        
                        # Calculate complexity and LOC
                        loc = 0
                        if comp.source_location:
                            source_paths = resolve_source_location(comp.source_location, project_root)
                            if not source_paths:
                                raise FileNotFoundError(f"Source not found: {comp.source_location}")
                            
                            # Pass component type for component-specific complexity rules
                            # Pass field_name for field components to analyze just that field
                            complexity_result = complexity_analyzer.analyze_files(
                                source_paths, 
                                component_type=comp_type,
                                field_name=field_name
                            )
                            label = complexity_result.complexity_label
                            loc = complexity_result.raw_metrics.loc
                        else:
                            # No source_location - cannot estimate
                            label = "unknown"
                        
                        # Calculate time estimate only if we have a source_location
                        if comp.source_location and loc > 0:
                            time_breakdown = time_metrics.get_hours(comp_type, label)
                            base_hours = time_breakdown.total
                            
                            # Apply time_factor to the calculated time estimate
                            adjusted_hours = base_hours * time_factor
                            
                            hours_int = int(adjusted_hours)
                            minutes = int((adjusted_hours - hours_int) * 60)
                            time_estimate = f"{hours_int}:{minutes:02d}"
                        else:
                            # No source_location or no code: time_estimate must be 0
                            time_estimate = "0:00"
                        
                        # Store tracking fields
                        comp_dict["complexity"] = label
                        comp_dict["loc"] = loc
                        comp_dict["time_estimate"] = time_estimate
                        
                        if "completion" not in comp_dict:
                            comp_dict["completion"] = "100%"
                        
                        components_enriched += 1
                        story_enriched_any = True
                        total_hours += adjusted_hours
                        print(f"      ✓ {label}, LOC: {loc}, {comp_dict['time_estimate']}")
                        
                    except FileNotFoundError as e:
                        error_msg = f"Source unavailable for {comp_dict.get('ref')}: {e}"
                        errors.append(error_msg)
                        logger.warning(error_msg)
                        print(f"      ⚠ {error_msg}")
                        comp_dict["complexity"] = "unknown"
                        comp_dict["loc"] = 0
                        comp_dict["time_estimate"] = "0:00"
                    
                    except Exception as e:
                        error_msg = f"Failed to analyze {comp_dict.get('ref')}: {e}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                        print(f"      ✗ {error_msg}")
                        comp_dict["complexity"] = "unknown"
                        comp_dict["loc"] = 0
                        comp_dict["time_estimate"] = "0:00"
                    
                    if "completion" not in comp_dict:
                        comp_dict["completion"] = "0%"
                
                # Set story status to done if any components were enriched
                if story_enriched_any:
                    story_data["enrich-status"] = "done"
                    feature_had_any_work = True
            
            # Only set feature status to done if feature itself needed estimation
            if should_estimate_feature and feature_had_any_work:
                feature_def["enrich-status"] = "done"
        
        # 5. Write updated TOML
        self._write_toml_file(map_file, toml_data)
        logger.info(f"Updated TOML: {map_file}")
        
        return {
            "backup_toml": backup_toml,
            "components_enriched": components_enriched,
            "total_hours": total_hours,
            "errors": errors,
        }

    def update_task_tables_in_place(
        self,
        project_root: Path,
        features_filter: list[str] | None = None,
        dry_run: bool = False,
        odoo_client: OdooClient | None = None,
    ) -> dict:
        """Update HTML tables in Odoo task descriptions without AI enrichment.
        
        This method regenerates only the HTML tables (complexity, effort, time)
        in Odoo task descriptions using data already present in the TOML file.
        No AI calls are made, and no changes are written to the TOML file.
        
        Use case: After manually updating complexity/time estimates in TOML,
        refresh the HTML tables in Odoo to reflect the changes.
        
        Args:
            project_root: Root directory of the project
            features_filter: List of feature names to update (None = all features)
            dry_run: If True, preview what would be updated without writing to Odoo
            odoo_client: OdooClient for writing to Odoo (required for non-dry-run)
        
        Returns:
            dict with results: {
                "features_updated": int,
                "user_stories_updated": int,
                "odoo_tasks_updated": int,
                "errors": list[str]
            }
        """
        map_file = project_root / "studio" / "feature_user_story_map.toml"
        
        # 1. Verify TOML exists
        if not map_file.exists():
            raise FileNotFoundError(f"feature_user_story_map.toml not found: {map_file}")
        
        # 2. For dry run, just count what would be updated
        if dry_run:
            loader = TomlLoader(project_root)
            features = loader.load_features()
            
            # Filter features if requested
            if features_filter:
                features = [f for f in features if f.name in features_filter]
            
            total_stories = sum(len(f.user_stories) for f in features)
            
            return {
                "features_updated": len(features),
                "user_stories_updated": total_stories,
                "odoo_tasks_updated": 0,
                "errors": [],
            }
        
        # 3. Validate Odoo client for non-dry-run
        if odoo_client is None:
            raise ValueError("OdooClient is required for non-dry-run table updates")
        
        # 4. Load TOML
        loader = TomlLoader(project_root)
        features = loader.load_features()
        
        # Filter features if requested
        if features_filter:
            features = [f for f in features if f.name in features_filter]
            print(f"\nFiltering to {len(features)} features: {', '.join(features_filter)}")
        
        # 5. Fetch timesheet data for all tasks
        print("\nFetching timesheet data from Odoo...")
        timesheet_data: dict[int, float] = {}
        for feature in features:
            if feature.task_id and feature.task_id > 0:
                try:
                    timesheet_data[feature.task_id] = odoo_client.fetch_task_timesheets(feature.task_id)
                except Exception as e:
                    logger.warning(f"Failed to fetch timesheets for feature task {feature.task_id}: {e}")
                    timesheet_data[feature.task_id] = 0.0
            
            for story in feature.user_stories:
                if story.task_id and story.task_id > 0:
                    try:
                        timesheet_data[story.task_id] = odoo_client.fetch_task_timesheets(story.task_id)
                    except Exception as e:
                        logger.warning(f"Failed to fetch timesheets for story task {story.task_id}: {e}")
                        timesheet_data[story.task_id] = 0.0
        
        print(f"✓ Fetched timesheet data for {len(timesheet_data)} tasks")
        
        # Helper: Calculate total hours for a user story from its components
        def calculate_story_total_hours(story: TomlUserStory) -> float:
            """Calculate total estimated hours from story components."""
            total_hours = 0.0
            for comp in story.components:
                time_estimate = getattr(comp, 'time_estimate', None) or '0:00'
                try:
                    time_str = str(time_estimate)
                    parts = time_str.split(":")
                    hours = float(parts[0]) + float(parts[1]) / 60 if len(parts) > 1 else float(parts[0])
                    total_hours += hours
                except (ValueError, IndexError):
                    pass
            return total_hours
        
        # 6. Update HTML tables in Odoo (no AI, no TOML changes)
        features_updated = 0
        user_stories_updated = 0
        odoo_tasks_updated = 0
        errors = []
        
        for feature in features:
            feature_name = feature.name
            feature_task_id = feature.task_id
            print(f"\nProcessing feature: {feature_name} (task_id: {feature_task_id})")
            
            # Update feature task HTML
            if feature_task_id > 0:
                try:
                    feature_html = OdooHtmlGenerator.generate_feature_html(
                        feature,
                        timesheet_data=timesheet_data,
                    )
                    odoo_client.write(
                        "project.task",
                        [feature_task_id],
                        {"description": feature_html}
                    )
                    odoo_tasks_updated += 1
                    features_updated += 1
                    print(f"  → Feature HTML tables: updated in Odoo task #{feature_task_id}")
                except OdooClientError as e:
                    error_msg = f"Failed to update feature '{feature_name}' in Odoo: {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    print(f"  ✗ {error_msg}")
            else:
                print(f"  → Feature: no task_id, skipping")
            
            # Update user story task HTML
            for story in feature.user_stories:
                story_name = story.name
                story_task_id = story.task_id
                
                if story_task_id > 0:
                    try:
                        story_html = OdooHtmlGenerator.generate_user_story_html(
                            story,
                            feature_name,
                            timesheet_data=timesheet_data,
                        )
                        # Calculate total estimate hours for allocated_hours field
                        total_estimate_hours = calculate_story_total_hours(story)
                        odoo_client.write(
                            "project.task",
                            [story_task_id],
                            {
                                "description": story_html,
                                "allocated_hours": total_estimate_hours,
                            }
                        )
                        odoo_tasks_updated += 1
                        user_stories_updated += 1
                        print(f"  → User Story '{story_name}': HTML tables updated in Odoo task #{story_task_id}")
                    except OdooClientError as e:
                        error_msg = f"Failed to update story '{story_name}' in Odoo: {e}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                        print(f"  ✗ {error_msg}")
                else:
                    print(f"  → User Story '{story_name}': no task_id, skipping")
        
        return {
            "features_updated": features_updated,
            "user_stories_updated": user_stories_updated,
            "odoo_tasks_updated": odoo_tasks_updated,
            "errors": errors,
        }

    def enrich_in_place(
        self,
        project_root: Path,
        dry_run: bool = False,
        odoo_client: OdooClient | None = None,
    ) -> dict:
        """Runs AI enrichment (writes to Odoo) AND effort estimation (writes to TOML).
        
        This is a convenience method that runs both enrich_stories_in_place()
        and estimate_effort_in_place() sequentially.
        
        - AI enrichment: Writes HTML descriptions to Odoo task descriptions
        - Effort estimation: Writes complexity/time to TOML
        
        Respects enrich-status field for selective enrichment control.
        
        Args:
            project_root: Root directory of the project
            dry_run: If True, verify connections only, don't enrich or write
            odoo_client: OdooClient for writing descriptions (required for non-dry-run)
        
        Returns:
            dict with combined results from both operations
        """
        errors = []
        
        # Run AI enrichment first (writes to Odoo)
        stories_result = self.enrich_stories_in_place(
            project_root, 
            dry_run=dry_run,
            odoo_client=odoo_client
        )
        errors.extend(stories_result.get("errors", []))
        
        # Then run effort estimation (writes to TOML)
        effort_result = self.estimate_effort_in_place(
            project_root, dry_run=dry_run
        )
        errors.extend(effort_result.get("errors", []))
        
        return {
            "backup_toml": stories_result.get("backup_toml") or effort_result.get("backup_toml"),
            "features_enriched": stories_result.get("features_enriched", 0),
            "user_stories_enriched": stories_result.get("user_stories_enriched", 0),
            "odoo_tasks_updated": stories_result.get("odoo_tasks_updated", 0),
            "components_enriched": effort_result.get("components_enriched", 0),
            "total_hours": effort_result.get("total_hours", 0.0),
            "errors": errors,
        }


def main():
    """CLI entry point for user story enricher.
    
    Updates feature_user_story_map.toml in-place with AI enrichment.
    Note: feature_user_story_map.toml is the primary source for user stories.
    """
    parser = argparse.ArgumentParser(
        description="Enrich feature_user_story_map.toml in-place with AI descriptions"
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Project root directory (contains studio/ folder)"
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        default="openai",
        help="AI provider to use"
    )
    parser.add_argument(
        "--model",
        help="Model name to use"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be enriched without making changes"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to enricher configuration TOML file"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s"
    )
    
    # Validate project root
    if not args.project_root.exists():
        logger.error(f"Project root not found: {args.project_root}")
        sys.exit(1)
    
    studio_dir = args.project_root / "studio"
    if not studio_dir.exists():
        logger.error(f"Studio folder not found: {studio_dir}")
        sys.exit(1)
    
    map_file = studio_dir / "feature_user_story_map.toml"
    if not map_file.exists():
        logger.error(f"feature_user_story_map.toml not found: {map_file}")
        sys.exit(1)
    
    # Load configuration
    if args.config and args.config.exists():
        config = EnricherConfig.from_file(args.config)
    else:
        config = EnricherConfig.default()
    
    # Override config with CLI args
    if args.provider:
        config.user_story_enricher.ai_provider = args.provider
    if args.model:
        config.user_story_enricher.model = args.model
    
    # Create enricher and run with new in-place method
    try:
        enricher = UserStoryEnricher(config)
        result = enricher.enrich_in_place(
            args.project_root,
            dry_run=args.dry_run,
        )
        
        if args.dry_run:
            print(f"\n📋 Dry run results:")
            print(f"   Would enrich:")
            print(f"     - {result['features_enriched']} features")
            print(f"     - {result['user_stories_enriched']} user stories")
            print(f"     - {result['components_enriched']} components")
        else:
            print(f"\n✅ Enrichment complete!")
            print(f"   Updated: feature_user_story_map.toml")
            print(f"\n   feature_user_story_map.toml is now ready for sync.")
            if result.get('errors'):
                print(f"   ⚠ Errors: {len(result['errors'])}")
            
    except AIProviderError as e:
        logger.error(f"AI provider error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
