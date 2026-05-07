"""Rename existing script parameters from hash-based names to readable names."""
import json
import re

from django.core.management.base import BaseCommand
from core.models import Script
from core.script_converter import _short_selector, _selector_hash


def _make_readable_name(old_name, selector):
    """Generate a readable name from selector, keeping the same prefix."""
    prefix = old_name.rsplit('_', 1)[0] if '_' in old_name else 'param'
    if selector:
        readable = _short_selector(selector)
        if len(readable) >= 2:
            return f'{prefix}_{readable}'
    return old_name


def _extract_selectors_from_steps(steps, parameters):
    """Build a mapping of param_name -> selector from step inputs."""
    param_selectors = {}
    for step in steps:
        inputs = step.get('inputs', {})
        step_params = step.get('parameters', [])
        selector = inputs.get('selector', '')

        for pname in step_params:
            if pname not in param_selectors and selector:
                param_selectors[pname] = selector

        # batch_action: look into nested actions
        for act in inputs.get('actions', []):
            act_selector = act.get('selector', '')
            # Find template references in action values
            for key, val in act.items():
                if isinstance(val, str):
                    for m in re.finditer(r'\{\{(\w+)\}\}', val):
                        pname = m.group(1)
                        if pname not in param_selectors and act_selector:
                            param_selectors[pname] = act_selector

    return param_selectors


def _rename_in_dict(d, old_name, new_name):
    """Recursively rename {{old_name}} to {{new_name}} in a dict/list structure."""
    old_ref = '{{' + old_name + '}}'
    new_ref = '{{' + new_name + '}}'
    if isinstance(d, dict):
        for k, v in list(d.items()):
            if isinstance(v, str) and old_ref in v:
                d[k] = v.replace(old_ref, new_ref)
            elif isinstance(v, (dict, list)):
                _rename_in_dict(v, old_name, new_name)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            if isinstance(v, str) and old_ref in v:
                d[i] = v.replace(old_ref, new_ref)
            elif isinstance(v, (dict, list)):
                _rename_in_dict(v, old_name, new_name)


class Command(BaseCommand):
    help = 'Rename existing script parameters from hash-based names (e.g. param_d6d32353) to readable names (e.g. param_username)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be renamed without making changes',
        )
        parser.add_argument(
            '--script-id', type=int,
            help='Only rename params for a specific script',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        script_id = options.get('script_id')

        qs = Script.objects.filter(status='active')
        if script_id:
            qs = qs.filter(pk=script_id)

        total_renamed = 0
        total_scripts = 0

        for script in qs:
            if not script.script_data:
                continue

            params = script.script_data.get('parameters', {})
            steps = script.script_data.get('steps', [])
            if not params:
                continue

            # Extract selectors from steps for each param
            param_selectors = _extract_selectors_from_steps(steps, params)

            # Build rename map: old_name -> new_name
            renames = {}
            for old_name in list(params.keys()):
                selector = param_selectors.get(old_name, '')
                new_name = _make_readable_name(old_name, selector)
                if new_name != old_name:
                    renames[old_name] = new_name

            if not renames:
                continue

            # Check for collisions: if two old names map to the same new name
            new_names = list(renames.values())
            seen = {}
            for old_name, new_name in renames.items():
                if new_name in seen:
                    # Collision — append hash suffix to both
                    selector = param_selectors.get(old_name, '')
                    other_selector = param_selectors.get(seen[new_name], '')
                    hash_suffix = _selector_hash(selector)[:4]
                    renames[old_name] = f'{new_name}_{hash_suffix}'
                    other_hash = _selector_hash(other_selector)[:4]
                    renames[seen[new_name]] = f'{new_name}_{other_hash}'
                else:
                    seen[new_name] = old_name

            self.stdout.write(f'\nScript #{script.id} "{script.name}":')
            for old_name, new_name in renames.items():
                self.stdout.write(f'  {old_name} → {new_name}')

            if dry_run:
                total_scripts += 1
                total_renamed += len(renames)
                continue

            # Apply renames to parameters dict
            new_params = {}
            for pname, pinfo in params.items():
                final_name = renames.get(pname, pname)
                new_params[final_name] = pinfo
            script.script_data['parameters'] = new_params

            # Apply renames to steps
            for step in steps:
                old_params_list = step.get('parameters', [])
                step['parameters'] = [renames.get(p, p) for p in old_params_list]
                for old_name, new_name in renames.items():
                    _rename_in_dict(step.get('inputs', {}), old_name, new_name)

            script.save(update_fields=['script_data'])
            total_scripts += 1
            total_renamed += len(renames)

        action = 'Would rename' if dry_run else 'Renamed'
        self.stdout.write(f'\n{action} {total_renamed} parameters across {total_scripts} scripts.')
