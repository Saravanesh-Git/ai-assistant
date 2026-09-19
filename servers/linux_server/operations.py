"""Shared, explicit operation dispatch for ordinary MCP calls and approved sudo jobs."""
from __future__ import annotations

from app.core.config import Settings
from security.path_policy import PathPolicy
from servers.linux_server import application_tools as apps, file_tools as files, system_tools as system

OPERATIONS = frozenset({
    'list_directory', 'read_text_file', 'create_directory', 'create_text_file',
    'write_text_file', 'move_path', 'copy_path', 'find_files', 'open_path',
    'open_application', 'open_browser_search', 'run_safe_command', 'run_command',
    'get_system_info', 'get_cpu_usage', 'get_memory_usage', 'get_disk_usage', 'get_battery_status',
})


def execute_operation(tool: str, arguments: dict, settings: Settings, *, elevated: bool = False):
    policy = PathPolicy()
    operations = {
        'list_directory': lambda **a: files.list_directory_data(policy=policy, **a),
        'read_text_file': lambda **a: files.read_text_file_data(policy=policy, max_size=settings.max_file_size, **a),
        'create_directory': lambda **a: files.create_directory_data(policy=policy, **a),
        'create_text_file': lambda **a: files.create_text_file_data(policy=policy, max_size=settings.max_file_size, **a),
        'write_text_file': lambda **a: files.write_text_file_data(policy=policy, max_size=settings.max_file_size, **a),
        'move_path': lambda **a: files.move_path_data(policy=policy, **a),
        'copy_path': lambda **a: files.copy_path_data(policy=policy, **a),
        'find_files': lambda **a: files.find_files_data(policy=policy, **a),
        'open_application': apps.open_application_data,
        'open_path': apps.open_path_data,
        'open_browser_search': apps.open_browser_search_data,
        'run_safe_command': apps.run_safe_command_data,
        'run_command': lambda **a: apps.run_command_data(timeout=settings.command_timeout_seconds, elevated=elevated, **a),
        'get_system_info': system.get_system_info_data,
        'get_cpu_usage': system.get_cpu_usage_data,
        'get_memory_usage': system.get_memory_usage_data,
        'get_disk_usage': system.get_disk_usage_data,
        'get_battery_status': system.get_battery_status_data,
    }
    if tool not in operations:
        raise ValueError('Unknown operation')
    try:
        return operations[tool](**arguments)
    except PermissionError as exc:
        if elevated:
            raise
        return {'elevation_required': True, 'reason': str(exc)}
