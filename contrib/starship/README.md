# starship prompt module

```toml
# ~/.config/starship.toml
[custom.token_finops]
command = "token-finops status --format starship --max-age 0"
when = "test -f ~/.token-finops/last.json"
format = "[$output]($style) "
style = "bold yellow"
shell = ["sh"]
```
Shows the binding constraint only (e.g. `CC 61% 2h!`). Keep the cache fresh with `contrib/refresh`.
