#!/usr/bin/env ruby
# Load the shared .odoo project configuration without adding a Python package dependency.

require "json"
require "shellwords"
require "yaml"

def fail_config(message)
  warn "Error: #{message}"
  exit 1
end

def load_yaml(path, required: true)
  unless File.file?(path)
    fail_config("Odoo configuration not found: #{path}") if required
    return {}
  end
  value = YAML.safe_load_file(path, permitted_classes: [], permitted_symbols: [], aliases: false)
  value ||= {}
  fail_config("#{path} must contain a YAML mapping") unless value.is_a?(Hash)
  value
rescue Psych::Exception => error
  fail_config("invalid YAML in #{path}: #{error.message}")
end

def deep_merge(left, right)
  left.merge(right) do |_key, old_value, new_value|
    old_value.is_a?(Hash) && new_value.is_a?(Hash) ? deep_merge(old_value, new_value) : new_value
  end
end

def dig_value(config, *path)
  path.reduce(config) { |value, key| value.is_a?(Hash) ? value[key] : nil }
end

def shell_export(name, value)
  return if value.nil?
  puts "export #{name}=#{Shellwords.escape(value.to_s)}"
end

command, config_path, override_path = ARGV
fail_config("usage: config.rb shell|json CONFIG [WORKTREE_OVERRIDE]") unless %w[shell json].include?(command) && config_path

config = load_yaml(config_path)
config = deep_merge(config, load_yaml(override_path, required: false)) if override_path
fail_config("config version must be 1") unless config["version"] == 1

if command == "json"
  puts JSON.generate(config)
  exit 0
end

mapping = {
  "PROJECT_NAME" => %w[project name],
  "ODOO_ROOT" => %w[odoo root],
  "ODOO_DATA_DIR" => %w[odoo data_dir],
  "ODOO_HTTP_INTERFACE" => %w[odoo http_interface],
  "ODOO_LIST_DB" => %w[odoo list_db],
  "ODOO_PROXY_MODE" => %w[odoo proxy_mode],
  "ODOO_LOG_LEVEL" => %w[odoo log_level],
  "BIN_PATH" => %w[odoo bin_path],
  "ODOO_SYNC_SCRIPT" => %w[odoo sync_script],
  "DB_NAME" => %w[database name],
  "DB_HOST" => %w[database host],
  "DB_PORT" => %w[database port],
  "DB_USER" => %w[database user],
  "HTTP_PORT" => %w[ports http],
  "TEST_HTTP_PORT" => %w[ports test_http],
  "TEST_GEVENT_PORT" => %w[ports test_gevent],
  "TEST_PORT_RANGE_START" => %w[ports test_range_start],
  "TEST_PORT_RANGE_END" => %w[ports test_range_end],
}

mapping.each { |name, path| shell_export(name, dig_value(config, *path)) }
