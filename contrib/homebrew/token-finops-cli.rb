class TokenFinopsCli < Formula
  include Language::Python::Virtualenv

  desc "Local-first token usage and budget-runway tracker for AI coding agents"
  homepage "https://github.com/tronicum/burn-token-burn"
  url "https://files.pythonhosted.org/packages/ac/a4/ff078907ad34c0b09b7597e394be8692f8eed430d080a02a9cd8ed1dfd90/token_finops_cli-0.2.0.tar.gz"
  sha256 "a1ee5422c3a828d9fe8b3763621fa21bc29f1423449e01d94d3c8732d20ebc22"
  license "AGPL-3.0-or-later"

  depends_on "python@3.12"

  # token-finops-cli has zero third-party dependencies (dependencies = [] in
  # pyproject.toml, stdlib only) so no `resource` blocks are needed beyond
  # the package itself.
  def install
    virtualenv_install_with_resources
  end

  test do
    help_text = shell_output("#{bin}/token-finops --help")
    assert_match "usage: token-finops", help_text
    assert_match "report", help_text
    assert_match "sessions", help_text
  end
end
