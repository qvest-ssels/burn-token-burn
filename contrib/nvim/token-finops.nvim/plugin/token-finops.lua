-- Auto-loaded by any plugin manager that adds this directory to 'runtimepath'
-- (lazy.nvim, packer, native :h packages). Defines the :TokenFinops command and
-- registers the health-check provider; the module itself is lazy-required so
-- opening Neovim never touches the filesystem until the command/health check runs.

if vim.g.loaded_token_finops then
  return
end
vim.g.loaded_token_finops = true

vim.api.nvim_create_user_command("TokenFinops", function()
  require("token-finops").open_float()
end, { desc = "Open the token-finops per-tool runway table" })
