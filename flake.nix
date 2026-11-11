{
  description = "App Builder for Odoo: a visual builder for Odoo whose output is real source code, developed with odoo-nix (addons mode)";

  inputs = {
    # flake-parts resolves perSystem `pkgs` from an input literally named `nixpkgs`.
    nixpkgs.follows = "odoo-nix/nixpkgs";

    # OCB and every repository the addons depend on, on this branch's series
    # (.odoo-series): source trees (`flake = false`) pinned by flake.lock.
    # `nix flake update` moves them; follow it with `odoo project relock`.
    # Generated from the addons' `depends`: keep it in step with them.
    ocb = {
      url = "github:OCA/OCB/18.0";
      flake = false;
    };
    # base_tier_validation and base_tier_validation_formula, for
    # app_builder_approval and app_builder_approval_formula. They move to a
    # repository of their own for 19.0.
    oca-server-ux = {
      url = "github:OCA/server-ux/18.0";
      flake = false;
    };
    # >>> odoo-nix: inputs (managed) >>>
    odoo-nix.url = "github:Avunu/odoo-nix/release-2";
    standards-profile = {
      url = "github:Avunu/odoo-standards-profile/v1";
      flake = false;
    };
    # <<< odoo-nix: inputs (managed) <<<
  };

  nixConfig = {
    extra-substituters = [ "https://devenv.cachix.org" ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  # Outputs:
  #   devShells.<system>.default  devenv: PostgreSQL, Odoo, Mailpit
  #   apps.<system>.relock        regenerate nix/pyproject.toml and nix/uv.lock
  outputs =
    { odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } (
      { ... }:
      {
        imports = [ odoo-nix.flakeModules.default ];

        systems = [
          "aarch64-darwin"
          "aarch64-linux"
          "x86_64-linux"
        ];

        perSystem =
          { lib, pkgs, ... }:
          {
            odoo-nix = {
              enable = true;
              name = "app-builder";
              workspaceRoot = ./.;
              # The one per-branch fact: the series this branch's code targets.
              odooSeries = lib.fileContents ./.odoo-series;
              addons.enable = true;
              # NixOS's github-runner service filters out the capset syscall. Under
              # that filter Chromium's GPU process fails to launch and every tour
              # times out on Emulation.setDeviceMetricsOverride; --no-zygote avoids it.
              testBrowser = pkgs.writeShellScriptBin "chromium" ''
                exec ${lib.getExe pkgs.chromium} --no-zygote "$@"
              '';
              coreSource = inputs.ocb;
              externalSources = [
                {
                  name = "server-ux";
                  src = inputs.oca-server-ux;
                }
              ];
            };

            # The addons' .js is compiled, not committed, so a fresh clone and
            # `odoo-nix gate test` both need it built before Odoo serves a page:
            # without it the console's bundle is empty. odoo-nix installs on
            # entry only outside CI, hence the cleared variable; the build
            # itself takes a fraction of a second.
            #
            # CI also runs the tools/ modules under typeguard (TYPING.md, Phase 1e).
            devenv.shells.default.enterShell = lib.mkAfter ''
              if [ -n "''${ODOO_NIX_CI:-}" ]; then
                export APP_BUILDER_TYPEGUARD=1
              fi
              (cd "$DEVENV_ROOT" && ODOO_NIX_CI= odoo-nix-node install && odoo-nix-node build >/dev/null) \
                || echo "app-builder: compiling the TypeScript failed; the console will not load" >&2
            '';
          };
      }
    );
}
