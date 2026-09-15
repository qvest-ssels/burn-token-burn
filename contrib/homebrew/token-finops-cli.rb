class TokenFinopsCli < Formula
  include Language::Python::Virtualenv

  desc "Local-first token usage and budget-runway tracker for AI coding agents"
  homepage "https://github.com/tronicum/burn-token-burn"
  url "https://files.pythonhosted.org/packages/00/c4/4c6617ecbe6fb08b1cff57d4cb51549fdbff2ac982a1d65087af9d630828/token_finops_cli-0.3.0.tar.gz"
  sha256 "b2d3d34c3a9eb4ef2f58a588c83484a74a6ba5df19c9d2d5e6a21081709708e7"
  license "AGPL-3.0-or-later"

  depends_on "python@3.12"

  # token-finops-cli has zero third-party dependencies (dependencies = [] in
  # pyproject.toml, stdlib only) so no `resource` blocks are needed beyond
  # the package itself.
  def install
    virtualenv_install_with_resources
  end

  test do
    # Assertions are pinned to subcommands actually present in the 0.3.0 sdist above.
    # `doctor` landed in the source repo's main branch AFTER this PyPI release was tagged
    # (it was merged post-release) -- it will be in a future release's pin, not this one.
    # Bump this list when url/sha256 above are bumped to a release that includes it.
    help_text = shell_output("#{bin}/token-finops --help")
    assert_match "usage: token-finops", help_text
    assert_match "report", help_text
    assert_match "sessions", help_text
    assert_match "adapters", help_text
  end
end
