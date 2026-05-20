# Development runtime config

Production/client installs do **not** write runtime secrets into this project folder.
They use the per-user config directory instead:

- Windows: `%APPDATA%\IndexAdvisor`
- Linux/macOS: `~/.config/index-advisor` or `$XDG_CONFIG_HOME/index-advisor`

For development, you may set:

```env
INDEX_ADVISOR_CONFIG_DIR=./config
```

Then the setup wizard will create `storage.env`, `credential.key`, and
`admin_token.env` here. Those files contain local secrets and must not be
committed or shared.

`STORAGE_DATABASE_URL` from the operating system environment still overrides the
saved `storage.env` file.
