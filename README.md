# Minify Lua

GitHub Action that minifies Lua files in place.

- Comments are removed.
- Whitespace that only affects readability is removed.
- Local variables, parameters, and loop variables are renamed to shorter names.
- Every token stays on its original line.
- Globals, table fields, and the implicit `self` on method definitions are left unchanged.

The action uses Python 3 from the runner. It has no third-party dependencies.

## Usage

```yaml
- uses: actions/checkout@v4
- uses: cybertk/minify-lua@v1
```

Skip extra directories, or minify only one subtree:

```yaml
- uses: cybertk/minify-lua@v1
  with:
    path: Addon
    exclude: .git,Libs,Embeds,Locale
```

## Local use

```bash
python3 minify_lua.py
python3 minify_lua.py --tracked
python3 minify_lua.py --exclude .git,Libs path/to/dir
```

`--tracked` limits the run to Lua files listed by `git ls-files`. Set `tracked: true` on the action for the same filter.
