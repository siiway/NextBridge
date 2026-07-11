{
  description = "NextBridge — 多平台聊天桥接工具开发环境";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python313
            uv
            ruff
            ty
          ];

          shellHook = ''
            export UV_PYTHON="${pkgs.python313}/bin/python3"
          '';
        };

        formatter = pkgs.nixfmt;
      }
    );
}
