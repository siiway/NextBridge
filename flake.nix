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

        # 本地 PostgreSQL 开发实例
        postgresql = pkgs.postgresql_17;

        # 本地实例默认参数（仅监听回环，数据存放在项目内 .pgdata）
        pgPort = "5432";
        pgUser = "nextbridge";
        pgDatabase = "nextbridge";

        # 初始化数据目录并创建开发数据库
        pg-init = pkgs.writeShellScriptBin "pg-init" ''
          set -euo pipefail
          if [ -d "$PGDATA" ]; then
            echo "PGDATA 已存在，跳过初始化：$PGDATA"
            exit 0
          fi
          echo "初始化 PostgreSQL 数据目录：$PGDATA"
          initdb --username="${pgUser}" --auth=trust --encoding=UTF8 --no-locale >/dev/null
          # 仅监听本地回环，unix socket 放在数据目录内，避免污染 /tmp
          {
            echo "listen_addresses = '127.0.0.1'"
            echo "port = ${pgPort}"
            echo "unix_socket_directories = '$PGDATA'"
          } >> "$PGDATA/postgresql.conf"
          echo "启动临时实例以创建数据库 ${pgDatabase}"
          pg_ctl start -w -o "-k \"$PGDATA\""
          createdb --host="$PGDATA" --username="${pgUser}" "${pgDatabase}" || true
          pg_ctl stop -w -m fast
          echo "初始化完成"
        '';

        # 启动本地实例
        pg-start = pkgs.writeShellScriptBin "pg-start" ''
          set -euo pipefail
          [ -d "$PGDATA" ] || pg-init
          pg_ctl start -w -l "$PGDATA/postgres.log" -o "-k \"$PGDATA\""
        '';

        # 停止本地实例
        pg-stop = pkgs.writeShellScriptBin "pg-stop" ''
          set -euo pipefail
          pg_ctl stop -w -m fast
        '';

        # 连接本地实例
        pg-psql = pkgs.writeShellScriptBin "pg-psql" ''
          exec psql --host="$PGDATA" --username="${pgUser}" "${pgDatabase}" "$@"
        '';
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python313
            uv
            ruff
            ty

            # PostgreSQL 及本地实例管理脚本
            postgresql
            pg-init
            pg-start
            pg-stop
            pg-psql
          ];

          shellHook = ''
            export UV_PYTHON="${pkgs.python313}/bin/python3"

            # 本地 PostgreSQL 连接参数（供 psql / 应用共享）
            export PGDATA="$PWD/.pgdata"
            export PGHOST="127.0.0.1"
            export PGPORT="${pgPort}"
            export PGUSER="${pgUser}"
            export PGDATABASE="${pgDatabase}"
            # 应用可读取此变量构造 SQLAlchemy database url
            export DATABASE_URL="postgresql://${pgUser}@127.0.0.1:${pgPort}/${pgDatabase}"

            echo "PostgreSQL 本地实例命令：pg-init / pg-start / pg-stop / pg-psql"
            echo "DATABASE_URL=$DATABASE_URL"
          '';
        };

        formatter = pkgs.nixfmt;
      }
    );
}
