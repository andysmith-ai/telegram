{
  description = "Telegram channel post store and CI publisher (stdlib Python)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "aarch64-darwin" "x86_64-darwin" "aarch64-linux" "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};
    in
    {
      packages = forAllSystems (system:
        let pkgs = pkgsFor system; in {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "telegram-publisher";
            version = "0.1.0";
            src = ./.;
            nativeBuildInputs = [ pkgs.makeWrapper ];
            buildInputs = [ pkgs.python3 ];
            installPhase = ''
              mkdir -p $out/lib/telegram-publisher
              cp -r publish $out/lib/telegram-publisher/
              makeWrapper ${pkgs.python3}/bin/python3 $out/bin/telegram-publish \
                --add-flags $out/lib/telegram-publisher/publish/publish.py
            '';
            meta.mainProgram = "telegram-publish";
          };
        });

      devShells = forAllSystems (system:
        let pkgs = pkgsFor system; in {
          default = pkgs.mkShell {
            packages = [ pkgs.python3 ];
          };
        });

      checks = forAllSystems (system:
        let pkgs = pkgsFor system; in {
          test = pkgs.stdenvNoCC.mkDerivation {
            pname = "telegram-publisher-tests";
            version = "0.1.0";
            src = ./.;
            buildInputs = [ pkgs.python3 ];
            doCheck = true;
            checkPhase = ''
              python3 -m unittest discover -s tests -v
            '';
            installPhase = "mkdir -p $out";
          };
        });
    };
}
