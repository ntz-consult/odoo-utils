"""Implementation Overview Generator for Odoo Project Sync.

Generates formatted HTML summary tables for all components in a feature user story map.
Creates two types of tables:
1. Component Type Summary: Aggregated data by type (quantity, total time)
2. Detailed Component Lists: Individual components grouped by type
"""

import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any


class ImplementationOverviewGenerator:
    """Generate implementation overview HTML from TOML data."""

    # Mapping of component types to display names
    COMPONENT_TYPE_DISPLAY = {
        "field": "Fields",
        "view": "Views",
        "server_action": "Server Actions",
        "automation": "Automations",
        "report": "Reports",
        "menu": "Menus",
        "security": "Security Rules",
        "data": "Data Records",
        "workflow": "Workflows",
        "custom": "Custom Components",
    }

    # Statistics explanation text
    STATISTICS_EXPLAINED = """
    <div style="background-color: #99c5b5; border-left: 4px solid #af2e00; padding: 20px; margin: 20px 0; line-height: 1.6;">
        <h2 style="color: #003339; margin-top: 0;">Statistics Explained</h2>
        
        <p>The information below represents the end result of a systematic journey from business need to working software. 
        The process begins with requirement gathering, where developers sit with business users to understand what's not 
        working and what needs to change. These conversations transform into specific requirements, each representing 
        something the software must accomplish.</p>
        
        <p>Next comes the translation phase, where business needs get broken down into technical components. A user's 
        request to "track products in two measurement units" becomes a specific list of fields to store data, views to 
        display information, automations to handle calculations, and validations to prevent errors. The team methodically 
        identifies every piece needed, which is how they arrive at counts like "44 fields" or "74 views."</p>
        
        <p>Each component then gets assessed for complexity and effort. Simple work like adding a basic field might take 
        twenty-four minutes, while complex calculations could require several hours. Developers draw on experience to 
        estimate both time and lines of code needed. These aren't guesses but informed predictions based on similar work 
        done previously.</p>
        
        <p>During development, each piece gets built and tested individually, then tested again as part of the complete 
        system. The team verifies everything works correctly and meets the original requirements before preparing 
        documentation and training materials for handover.</p>
        
        <p>Finally, actual users test the system in realistic conditions during user acceptance testing. The development 
        team supports them closely, addressing issues and ensuring the software genuinely supports their daily work rather 
        than hindering it.</p>
        
        <p style="margin-bottom: 0;"><strong>The final numbers you see represent accumulated estimates across this entire 
        lifecycle, capturing scope, technical depth, and human effort required to deliver working software.</strong></p>
    </div>
    """

    def __init__(self, toml_path: Path, timesheet_data: dict[int, float] | None = None):
        """Initialize the generator.

        Args:
            toml_path: Path to feature_user_story_map.toml
            timesheet_data: Dict mapping task_id to actual hours (optional)
        """
        self.toml_path = toml_path
        self.timesheet_data = timesheet_data or {}
        self.components_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.type_summaries: dict[str, dict[str, Any]] = {}
        self.overall_estimate_minutes = 0
        self.overall_actual_minutes = 0

    def load_and_analyze(self) -> None:
        """Load TOML data and analyze components."""
        with open(self.toml_path, "rb") as f:
            toml_data = tomllib.load(f)

        # Collect all components from all user stories
        features = toml_data.get("features", {})
        
        # Track all task IDs for actual time calculation
        all_task_ids = set()
        
        for feature_name, feature_def in features.items():
            # Add feature task_id if present
            if feature_def.get("task_id"):
                all_task_ids.add(feature_def["task_id"])
            
            user_stories = feature_def.get("user_stories", [])
            
            # Handle both dict format (new) and list format (legacy)
            if isinstance(user_stories, dict):
                story_list = list(user_stories.values())
            else:
                story_list = user_stories
            
            for story in story_list:
                # Add story task_id if present
                if story.get("task_id"):
                    all_task_ids.add(story["task_id"])
                
                components = story.get("components", [])
                
                for component in components:
                    ref = component.get("ref", "")
                    component_type = self._extract_component_type(ref)
                    
                    # Add to components by type
                    self.components_by_type[component_type].append({
                        "ref": ref,
                        "complexity": component.get("complexity", "unknown"),
                        "loc": component.get("loc", 0),
                        "time_estimate": component.get("time_estimate", "0:00"),
                        "completion": component.get("completion", "0%"),
                        "source_location": component.get("source_location", ""),
                    })

        # Calculate summaries
        self._calculate_summaries()
        
        # Calculate overall actual time from timesheet data
        for task_id in all_task_ids:
            actual_hours = self.timesheet_data.get(task_id, 0.0)
            self.overall_actual_minutes += int(actual_hours * 60)

    def _extract_component_type(self, ref: str) -> str:
        """Extract component type from ref string.

        Args:
            ref: Component reference (e.g., "field.sale_order.x_custom")

        Returns:
            Component type (e.g., "field")
        """
        if "." in ref:
            return ref.split(".", 1)[0]
        return "custom"

    def _parse_time_estimate(self, time_str: str) -> int:
        """Parse time estimate string to minutes.

        Args:
            time_str: Time string in format "HH:MM" or "H:MM"

        Returns:
            Total minutes
        """
        try:
            if ":" in time_str:
                parts = time_str.split(":")
                hours = int(parts[0])
                minutes = int(parts[1])
                return hours * 60 + minutes
        except (ValueError, IndexError):
            pass
        return 0

    def _format_time(self, total_minutes: int) -> str:
        """Format minutes to HH:MM string.

        Args:
            total_minutes: Total minutes

        Returns:
            Formatted time string "HH:MM"
        """
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours:02d}:{minutes:02d}"

    def _calculate_summaries(self) -> None:
        """Calculate summary statistics for each component type."""
        for component_type, components in self.components_by_type.items():
            total_minutes = sum(
                self._parse_time_estimate(comp["time_estimate"])
                for comp in components
            )
            total_loc = sum(
                comp["loc"]
                for comp in components
            )
            
            self.type_summaries[component_type] = {
                "quantity": len(components),
                "total_loc": total_loc,
                "total_time": self._format_time(total_minutes),
                "total_minutes": total_minutes,
            }
            
            # Accumulate overall estimate
            self.overall_estimate_minutes += total_minutes

    def generate_component_type_summary_table(self) -> str:
        """Generate Table 1: Component Type Summary.

        Returns:
            HTML table string
        """
        html = []
        html.append('<h2 style="color: #003339; border-bottom: 2px solid #af2e00; padding-bottom: 10px; margin-top: 30px;">Component Type Summary</h2>')
        html.append('<table border="0" cellpadding="12" cellspacing="0" style="border-collapse: collapse; width: 100%; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 20px 0;">')
        html.append('  <thead style="background-color: #003339; color: white;">')
        html.append('    <tr>')
        html.append('      <th style="text-align: left; font-weight: 600; border-bottom: 2px solid #af2e00;">Type</th>')
        html.append('      <th style="text-align: right; font-weight: 600; border-bottom: 2px solid #af2e00;">Quantity</th>')
        html.append('      <th style="text-align: right; font-weight: 600; border-bottom: 2px solid #af2e00;">Lines of Code</th>')
        html.append('      <th style="text-align: right; font-weight: 600; border-bottom: 2px solid #af2e00;">Total Time</th>')
        html.append('    </tr>')
        html.append('  </thead>')
        html.append('  <tbody>')

        # Sort by component type name
        sorted_types = sorted(self.type_summaries.keys())
        total_quantity = 0
        total_loc = 0
        total_minutes = 0

        for idx, component_type in enumerate(sorted_types):
            summary = self.type_summaries[component_type]
            display_name = self.COMPONENT_TYPE_DISPLAY.get(
                component_type, component_type.title()
            )
            
            total_quantity += summary["quantity"]
            total_loc += summary["total_loc"]
            total_minutes += summary["total_minutes"]
            
            # Alternating row colors
            row_color = "#ffffff" if idx % 2 == 0 else "#99c5b5"
            html.append(f'    <tr style="background-color: {row_color};">')
            html.append(f'      <td style="padding: 10px; border-bottom: 1px solid #899e8b;"><strong>{display_name}</strong></td>')
            html.append(f'      <td style="text-align: right; padding: 10px; border-bottom: 1px solid #899e8b;">{summary["quantity"]}</td>')
            html.append(f'      <td style="text-align: right; padding: 10px; border-bottom: 1px solid #899e8b;">{summary["total_loc"]:,}</td>')
            html.append(f'      <td style="text-align: right; padding: 10px; border-bottom: 1px solid #899e8b; font-family: monospace;">{summary["total_time"]}</td>')
            html.append('    </tr>')

        # Add totals row
        total_time_formatted = self._format_time(total_minutes)
        html.append('    <tr style="font-weight: bold; background-color: #afece7; border-top: 3px solid #af2e00;">')
        html.append('      <td style="padding: 12px; font-size: 1.1em; color: #003339;">TOTAL</td>')
        html.append(f'      <td style="text-align: right; padding: 12px; font-size: 1.1em; color: #003339;">{total_quantity}</td>')
        html.append(f'      <td style="text-align: right; padding: 12px; font-size: 1.1em; color: #003339;">{total_loc:,}</td>')
        html.append(f'      <td style="text-align: right; padding: 12px; font-size: 1.1em; color: #003339; font-family: monospace;">{total_time_formatted}</td>')
        html.append('    </tr>')

        html.append('  </tbody>')
        html.append('</table>')
        
        return "\n".join(html)

    def generate_detailed_component_tables(self) -> str:
        """Generate Table 2: Detailed Component Lists (one per type).

        Returns:
            HTML string with multiple tables
        """
        html = []
        html.append('<h2 style="color: #003339; border-bottom: 2px solid #af2e00; padding-bottom: 10px; margin-top: 40px;">Detailed Component Lists</h2>')

        # Sort by component type name
        sorted_types = sorted(self.components_by_type.keys())

        for component_type in sorted_types:
            components = self.components_by_type[component_type]
            display_name = self.COMPONENT_TYPE_DISPLAY.get(
                component_type, component_type.title()
            )
            
            # Sort components by time_estimate (descending)
            sorted_components = sorted(
                components,
                key=lambda c: self._parse_time_estimate(c["time_estimate"]),
                reverse=True
            )

            html.append(f'<h3 style="color: #003339; margin-top: 30px; margin-bottom: 15px; padding-left: 10px; border-left: 4px solid #af2e00;">{display_name}</h3>')
            html.append('<table border="0" cellpadding="10" cellspacing="0" style="border-collapse: collapse; width: 100%; margin-bottom: 30px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">')
            html.append('  <thead style="background-color: #899e8b; color: white;">')
            html.append('    <tr>')
            html.append('      <th style="text-align: left; font-weight: 600; border-bottom: 2px solid #af2e00;">Ref</th>')
            html.append('      <th style="text-align: center; font-weight: 600; border-bottom: 2px solid #af2e00;">Complexity</th>')
            html.append('      <th style="text-align: right; font-weight: 600; border-bottom: 2px solid #af2e00;">Lines of Code</th>')
            html.append('      <th style="text-align: right; font-weight: 600; border-bottom: 2px solid #af2e00;">Time Estimate</th>')
            html.append('      <th style="text-align: center; font-weight: 600; border-bottom: 2px solid #af2e00;">Completion</th>')
            html.append('    </tr>')
            html.append('  </thead>')
            html.append('  <tbody>')

            for idx, component in enumerate(sorted_components):
                # Apply color coding for complexity
                complexity = component["complexity"]
                complexity_color = self._get_complexity_color(complexity)
                row_color = "#ffffff" if idx % 2 == 0 else "#99c5b5"
                
                html.append(f'    <tr style="background-color: {row_color};">')
                html.append(f'      <td style="font-family: monospace; font-size: 0.9em; padding: 8px; border-bottom: 1px solid #899e8b;">{component["ref"]}</td>')
                html.append(f'      <td style="text-align: center; background-color: {complexity_color}; padding: 8px; border-bottom: 1px solid #899e8b; font-weight: 600; border-radius: 4px;">{complexity}</td>')
                html.append(f'      <td style="text-align: right; padding: 8px; border-bottom: 1px solid #899e8b;">{component["loc"]:,}</td>')
                html.append(f'      <td style="text-align: right; font-family: monospace; padding: 8px; border-bottom: 1px solid #899e8b;">{component["time_estimate"]}</td>')
                html.append(f'      <td style="text-align: center; padding: 8px; border-bottom: 1px solid #899e8b;">{component["completion"]}</td>')
                html.append('    </tr>')

            html.append('  </tbody>')
            html.append('</table>')

        return "\n".join(html)

    def _get_complexity_color(self, complexity: str) -> str:
        """Get background color for complexity level.

        Args:
            complexity: Complexity level (simple, medium, complex)

        Returns:
            CSS color code
        """
        color_map = {
            "simple": "#afece7",  # Icy Aqua (light, positive)
            "medium": "#99c5b5",  # Muted Teal 2 (medium)
            "complex": "#af2e00",  # Rusty Spice (strong, attention)
        }
        return color_map.get(complexity.lower(), "#899e8b")

    def generate_overall_totals_table(self) -> str:
        """Generate overall totals table with estimates and actuals.
        
        Returns:
            HTML table string
        """
        html = []
        
        # Format times
        estimate_time = self._format_time(self.overall_estimate_minutes)
        actual_time = self._format_time(self.overall_actual_minutes)
        
        html.append('<table border="0" cellpadding="12" cellspacing="0" style="border-collapse: collapse; width: 600px; margin: 30px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">')
        html.append('  <tbody>')
        
        # Estimate row
        html.append('    <tr style="background-color: #ffffff;">')
        html.append('      <td style="padding: 12px; border-bottom: 1px solid #899e8b; font-weight: 600; color: #003339;">Overall Total Estimate Time</td>')
        html.append(f'      <td style="text-align: right; padding: 12px; border-bottom: 1px solid #899e8b; font-family: monospace; font-size: 1.1em; color: #003339;">{estimate_time}</td>')
        html.append('    </tr>')
        
        # Actual row
        html.append('    <tr style="background-color: #99c5b5;">')
        html.append('      <td style="padding: 12px; font-weight: 600; color: #003339;">Overall Total Actual Time</td>')
        html.append(f'      <td style="text-align: right; padding: 12px; font-family: monospace; font-size: 1.1em; color: #003339;">{actual_time}</td>')
        html.append('    </tr>')
        
        html.append('  </tbody>')
        html.append('</table>')
        
        return "\n".join(html)

    def generate_full_html(self) -> str:
        """Generate complete HTML description for Implementation Overview task.

        Returns:
            Complete HTML string
        """
        html = []
        
        html.append('<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">')
        html.append('<h1 style="color: #003339; font-size: 2.5em; margin-bottom: 10px; border-bottom: 3px solid #af2e00; padding-bottom: 15px;">Implementation Overview</h1>')
        
        # Add Overall Totals table at the top
        html.append(self.generate_overall_totals_table())
        
        # Add Statistics Explained section
        html.append(self.STATISTICS_EXPLAINED)
        
        # Table 1: Component Type Summary
        html.append(self.generate_component_type_summary_table())
        html.append('<br/>')
        
        # Table 2: Detailed Component Lists
        html.append(self.generate_detailed_component_tables())
        
        html.append('</div>')
        
        return "\n".join(html)

    @classmethod
    def generate_from_toml(cls, toml_path: Path, timesheet_data: dict[int, float] | None = None) -> str:
        """Convenience method to generate HTML from TOML file.

        Args:
            toml_path: Path to feature_user_story_map.toml
            timesheet_data: Dict mapping task_id to actual hours (optional)

        Returns:
            Complete HTML string
        """
        generator = cls(toml_path, timesheet_data)
        generator.load_and_analyze()
        return generator.generate_full_html()
