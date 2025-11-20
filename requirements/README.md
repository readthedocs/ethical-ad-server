# Dependency Management

## Migration to uv

This project has migrated from pip-tools to [uv](https://docs.astral.sh/uv/) for dependency management.

### Previous Setup (pip-tools)

Previously, dependencies were managed using pip-tools with separate `.in` files that were compiled to `.txt` files.

### New Setup (uv + pyproject.toml)

Dependencies are now managed in `pyproject.toml` using [PEP 621](https://peps.python.org/pep-0621/) format with dependency groups:

- **Base dependencies**: Core application dependencies (in `[project.dependencies]`)
- **Production**: Production-specific dependencies (`[project.optional-dependencies.production]`)
- **Analyzer**: ML/analyzer dependencies (`[project.optional-dependencies.analyzer]`)
- **Dev**: Development and testing dependencies (`[project.optional-dependencies.dev]`)

### Benefits of uv

1. **Single source of truth**: All dependencies in `pyproject.toml` instead of multiple `.in` files
2. **No version conflicts**: `uv sync` installs all dependency groups together, ensuring compatibility
3. **Faster installation**: 10-100x faster than pip
4. **Better resolution**: Improved dependency resolver that handles complex constraints
5. **Reproducible builds**: `uv.lock` ensures exact versions across environments

### Working with Dependencies

#### Installing Dependencies

```bash
# Install all dependencies including dev tools
uv sync --all-extras

# Install only production dependencies
uv sync --no-dev --extra production

# Install with analyzer dependencies
uv sync --no-dev --extra production --extra analyzer
```

#### Adding New Dependencies

1. Add the dependency to the appropriate section in `pyproject.toml`
2. Run `uv lock` to update `uv.lock`
3. Run `uv sync` to install the new dependency

#### Updating Dependencies

```bash
# Update all dependencies to latest compatible versions
uv lock --upgrade

# Update a specific package
uv lock --upgrade-package <package-name>
```

#### Running Commands

Use `uv run` to run commands in the uv-managed environment:

```bash
uv run python manage.py migrate
uv run pytest
uv run tox
```

### Pre-commit Hook

The `uv.lock` file is automatically kept in sync via pre-commit hooks. When you commit changes to `pyproject.toml`, the pre-commit hook will update `uv.lock` if needed.

### Legacy Files

The old `requirements/*.in` and `requirements/*.txt` files are kept for reference during the migration period but are no longer used. They will be removed in a future cleanup.
