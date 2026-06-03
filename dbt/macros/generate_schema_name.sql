{# Override dbt's default schema generator so `+schema: staging` puts
   models in `staging.*` rather than `<target_schema>_staging.*`. The
   default macro appends; we want a hard override so our schema names
   match the migrations exactly. #}

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
