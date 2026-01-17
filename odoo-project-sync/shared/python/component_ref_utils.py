"""Component Reference Utilities.

Provides normalization and matching utilities for component references
used in feature_user_story_map.toml and extracted components.
"""

import re
from typing import Dict, List, Optional, Tuple

from feature_detector import Component


class ComponentRefUtils:
    """Utilities for normalizing and matching component references."""

    @staticmethod
    def normalize_reference(ref: str) -> str:
        """Normalize a component reference for consistent matching.

        Simply trim whitespace and lowercase. Do NOT strip parts of the name
        as they are integral to the component identity.

        Args:
            ref: Raw component reference string

        Returns:
            Normalized reference string (trimmed and lowercased)
        """
        # Trim and lowercase only - preserve the full name
        return ref.strip().lower()
    
    @staticmethod
    def normalize_name_for_filename(name: str) -> str:
        """Normalize a component name to match typical filename conventions.
        
        Converts a component name like "[bom] Populate Variant BoMs (Dynabraid)"
        to match filename like "[bom]_populate_variant_boms_(dynabraid).py"
        
        Args:
            name: Component name or display name
            
        Returns:
            Normalized name matching filename conventions (lowercase, underscores)
        """
        # Convert to lowercase
        normalized = name.lower()
        # Replace spaces with underscores
        normalized = normalized.replace(" ", "_")
        # Keep brackets, parens, and other special chars as-is
        # This matches Odoo Studio's filename generation
        return normalized

    @staticmethod
    def parse_normalized_reference(ref: str) -> Tuple[str, Optional[str], str]:
        """Parse a normalized reference into type, model, name components.

        Reference format is: type.model.name where:
        - type is the component type (field, view, server_action, etc.)
        - model is the Odoo model with underscores (res_partner)
        - name is everything after the second dot (may contain dots, spaces, colons, etc.)

        Args:
            ref: Normalized reference string

        Returns:
            Tuple of (type, model, name) where model may be None
        """
        # Split on dots, but only use the first two as type and model
        # Everything after that is part of the name
        parts = ref.split(".", 2)  # maxsplit=2 to get at most 3 parts
        
        if len(parts) < 2:
            # Malformed or legacy format: just "type" or empty
            return parts[0] if parts else "", None, ""
        elif len(parts) == 2:
            # type.name format (no model)
            return parts[0], None, parts[1]
        else:
            # type.model.name format (parts[2] contains full name with any dots)
            return parts[0], parts[1], parts[2]

    @staticmethod
    def generate_candidate_keys(type_part: str, model_part: Optional[str], name_part: str) -> List[str]:
        """Generate candidate keys for matching, including model variants.

        Args:
            type_part: Component type (e.g., 'field')
            model_part: Model name (may be None)
            name_part: Component name

        Returns:
            List of candidate reference strings to try
        """
        candidates = []

        if model_part:
            # Generate BOTH dot and underscore variants since:
            # - TOML might use: stock_move_line (underscores)
            # - Source might have: stock.move.line (dots)
            # We need to try all combinations
            
            # Original format (as-is from TOML)
            candidates.append(f"{type_part}.{model_part}.{name_part}")
            
            # Convert dots to underscores
            model_underscore = model_part.replace(".", "_")
            if model_underscore != model_part:
                candidates.append(f"{type_part}.{model_underscore}.{name_part}")
            
            # Convert underscores to dots
            model_dotted = model_part.replace("_", ".")
            if model_dotted != model_part:
                candidates.append(f"{type_part}.{model_dotted}.{name_part}")
        else:
            # type.name (fallback)
            candidates.append(f"{type_part}.{name_part}")

        return candidates

    @staticmethod
    def find_component_by_reference(ref: str, components: List[Component]) -> Optional[Component]:
        """Find a component by its reference string using normalization.
        
        The TOML reference format is: type.model.name
        But since both model and name can contain dots, we try multiple parsing strategies.

        Args:
            ref: Component reference string from TOML
            components: List of extracted Component objects

        Returns:
            Matching Component or None
        """
        # Normalize the reference
        normalized = ComponentRefUtils.normalize_reference(ref)
        
        # Parse the reference to get parts for advanced matching
        ref_type, ref_model, ref_name = ComponentRefUtils.parse_normalized_reference(normalized)
        ref_name_as_filename = ComponentRefUtils.normalize_name_for_filename(ref_name)
        
        # Strategy: Compare directly against all components
        # Build keys from components and match against normalized ref
        for comp in components:
            comp_type_str = comp.component_type.value.lower()
            
            # Check for filename match (handles Studio exports)
            # SourceComponent objects have file_path, Component objects might have it in raw_data
            file_path = getattr(comp, "file_path", None)
            if not file_path and hasattr(comp, "raw_data") and isinstance(comp.raw_data, dict):
                file_path = comp.raw_data.get("file_path")

            if file_path:
                from pathlib import Path
                filename = Path(file_path).stem
                
                if filename == ref_name_as_filename:
                    # Name matches via filename!
                    # Check type
                    if comp_type_str == ref_type:
                        # Check model compatibility
                        comp_model_norm = comp.model.lower() if comp.model else ""
                        ref_model_norm = ref_model.lower() if ref_model else ""
                        
                        # Match if:
                        # 1. Models match exactly (or with underscore/dot variations)
                        # 2. Component has generic model (ir.actions.server)
                        # 3. Component has no model
                        
                        model_matches = (
                            comp_model_norm == ref_model_norm or
                            comp_model_norm.replace(".", "_") == ref_model_norm or
                            comp_model_norm.replace("_", ".") == ref_model_norm or
                            comp_model_norm == "ir.actions.server" or
                            comp_model_norm == "base.automation" or
                            not comp_model_norm
                        )
                        
                        if model_matches:
                            return comp

            # Build all possible component keys (with name and display_name)
            comp_keys = []
            
            if comp.model:
                # Standard key: type.model.name
                comp_keys.append(f"{comp_type_str}.{comp.model}.{comp.name}".lower())
                
                # Model with underscores instead of dots
                model_underscore = comp.model.replace(".", "_")
                if model_underscore != comp.model:
                    comp_keys.append(f"{comp_type_str}.{model_underscore}.{comp.name}".lower())
                
                # Model with dots instead of underscores
                model_dotted = comp.model.replace("_", ".")
                if model_dotted != comp.model:
                    comp_keys.append(f"{comp_type_str}.{model_dotted}.{comp.name}".lower())
                
                # Also try display_name if different
                if comp.display_name and comp.display_name != comp.name:
                    comp_keys.append(f"{comp_type_str}.{comp.model}.{comp.display_name}".lower())
                    if model_underscore != comp.model:
                        comp_keys.append(f"{comp_type_str}.{model_underscore}.{comp.display_name}".lower())
                    if model_dotted != comp.model:
                        comp_keys.append(f"{comp_type_str}.{model_dotted}.{comp.display_name}".lower())
            else:
                # No model - just type.name
                comp_keys.append(f"{comp_type_str}.{comp.name}".lower())
                if comp.display_name and comp.display_name != comp.name:
                    comp_keys.append(f"{comp_type_str}.{comp.display_name}".lower())
            
            # Check if normalized ref matches any component key
            if normalized in comp_keys:
                return comp

        # Fallback: Try matching by model+name across component types
        # This handles cases where TOML incorrectly labels automations as server_actions
        # Parse reference to extract model and name (try different split points)
        parts = normalized.split(".")
        if len(parts) >= 3:
            # Try different combinations of where model ends and name begins
            type_part = parts[0]
            
            # Try: type.model.name (model is parts[1], name is rest)
            model_guess = parts[1]
            name_guess = ".".join(parts[2:])
            
            for comp in components:
                comp_model_normalized = comp.model.replace(".", "_").replace("_", ".").lower() if comp.model else ""
                comp_name_lower = comp.name.lower()
                comp_display_lower = comp.display_name.lower() if comp.display_name else ""
                
                # Check if model and name match (ignoring type)
                model_matches = (
                    comp_model_normalized == model_guess or
                    comp_model_normalized.replace(".", "_") == model_guess or
                    comp_model_normalized.replace("_", ".") == model_guess
                )
                name_matches = (
                    comp_name_lower == name_guess or
                    comp_display_lower == name_guess
                )
                
                if model_matches and name_matches:
                    return comp
        
        # Final fallback: Filename-based matching
        # For server actions and automations, try matching against filenames
        # Example: "[bom] Populate Variant BoMs (Dynabraid)" should match
        #          "[bom]_populate_variant_boms_(dynabraid).py"
        if len(parts) >= 3:
            type_part = parts[0]
            model_guess = parts[1]
            name_guess = ".".join(parts[2:])
            
            # Normalize the name to filename format
            normalized_filename = ComponentRefUtils.normalize_name_for_filename(name_guess)
            
            # Generic models that should be treated as "wildcard" for matching
            # When a component has these models, it means the actual target model
            # couldn't be determined from the source, so we should still try to match by name
            generic_models = {"ir.actions.server", "ir_actions_server", "base.automation", "base_automation"}
            
            for comp in components:
                comp_type_str = comp.component_type.value.lower()
                
                # Type must match
                if comp_type_str != type_part:
                    continue
                
                # Model must match (with flexibility for dots/underscores)
                # OR component has a generic model (meaning target model wasn't determined)
                comp_model_normalized = comp.model.replace(".", "_").replace("_", ".").lower() if comp.model else ""
                comp_model_underscore = comp.model.replace(".", "_").lower() if comp.model else ""
                model_matches = (
                    comp_model_normalized == model_guess or
                    comp_model_normalized.replace(".", "_") == model_guess or
                    comp_model_normalized.replace("_", ".") == model_guess
                )
                
                # Allow matching if component has a generic model (target model unknown)
                has_generic_model = comp_model_underscore in generic_models or comp_model_normalized in generic_models
                
                if not model_matches and not has_generic_model:
                    continue
                
                # Check if component's file_path (from raw_data) contains the normalized filename
                file_path = comp.raw_data.get("file_path") if isinstance(comp.raw_data, dict) else None
                if file_path:
                    # Extract just the filename without extension
                    from pathlib import Path
                    filename_stem = Path(file_path).stem.lower()
                    
                    # Check if the normalized name matches the filename
                    if normalized_filename == filename_stem:
                        return comp
                
                # Also try normalizing the component's name and checking against ref
                comp_name_normalized = ComponentRefUtils.normalize_name_for_filename(comp.name)
                comp_display_normalized = ComponentRefUtils.normalize_name_for_filename(comp.display_name) if comp.display_name else ""
                
                if normalized_filename == comp_name_normalized or normalized_filename == comp_display_normalized:
                    return comp

        return None

    @staticmethod
    def fuzzy_match_component(ref: str, components: List[Component], max_suggestions: int = 3) -> List[Component]:
        """Perform fuzzy matching for component references.

        Args:
            ref: Component reference string
            components: List of Component objects
            max_suggestions: Maximum number of suggestions to return

        Returns:
            List of suggested Component matches
        """
        normalized = ComponentRefUtils.normalize_reference(ref)
        type_part, model_part, name_part = ComponentRefUtils.parse_normalized_reference(normalized)

        suggestions = []
        name_lower = name_part.lower()

        for comp in components:
            comp_type_str = comp.component_type.value.lower()

            # Type must match
            if comp_type_str != type_part:
                continue

            # Score based on name similarity
            comp_name_lower = comp.name.lower()
            comp_display_lower = comp.display_name.lower() if comp.display_name else ""

            score = 0
            if name_lower == comp_name_lower or name_lower == comp_display_lower:
                score = 100  # Exact match
            elif name_lower in comp_name_lower or name_lower in comp_display_lower:
                score = 50  # Substring match
            elif comp_name_lower in name_lower or comp_display_lower in name_lower:
                score = 25  # Contains match

            if score > 0:
                suggestions.append((comp, score))

        # Sort by score descending and return top matches
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [comp for comp, score in suggestions[:max_suggestions]]