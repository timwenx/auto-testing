"""Data migration: copy ExecutionRecord.replay_script → Script model"""

from django.db import migrations


def migrate_replay_scripts_to_script_model(apps, schema_editor):
    ExecutionRecord = apps.get_model('core', 'ExecutionRecord')
    Script = apps.get_model('core', 'Script')

    # Only migrate records that have replay_script data and haven't already been migrated
    records = ExecutionRecord.objects.filter(replay_script__isnull=False).exclude(replay_script={})
    for record in records:
        # Skip if a Script already exists for this source_execution
        if Script.objects.filter(source_execution=record).exists():
            continue

        script_data = record.replay_script
        if not isinstance(script_data, dict) or not script_data:
            continue

        # Derive name and feature_group from related objects
        name = ''
        feature_group = ''
        if record.testcase:
            name = record.testcase.name or f'脚本-{record.pk}'
            feature_group = getattr(record.testcase, 'feature_group', '') or ''
        else:
            name = f'脚本-{record.pk}'

        Script.objects.create(
            project_id=record.project_id,
            testcase_id=record.testcase_id,
            source_execution_id=record.pk,
            name=name,
            feature_group=feature_group,
            script_data=script_data,
            status='active',
            version=1,
        )


def reverse_migrate(apps, schema_editor):
    """No-op reverse — Script records created by data migration stay in place."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_add_plan_execution'),
    ]

    operations = [
        migrations.RunPython(migrate_replay_scripts_to_script_model, reverse_migrate),
    ]
