/**
 * Build the thing a restaurant actually installs.
 *
 * Produces `release/QuickBitePrintAgent-<version>-win-x64.zip` containing one
 * self-contained executable and the two scripts that register it. No Node on
 * the target PC, no npm, no folder of dependencies — because the person doing
 * this is standing in a kitchen and the answer to "what do I install" has to
 * be one file.
 *
 * How the executable is made: Node's single-executable support bakes the
 * bundled script into a copy of `node.exe` as a resource. It is why the file
 * is ~90MB — that is the Node runtime, not our code, which is 278KB.
 *
 *   node scripts-package.mjs
 */

import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const version = JSON.parse(readFileSync(join(here, "package.json"), "utf8")).version;
const build = join(here, "build");
const release = join(here, "release");
const exeName = "QuickBitePrintAgent.exe";

function run(command, args) {
  process.stdout.write(`  ${command} ${args.join(" ")}\n`);
  // `shell` only for the npm-family launchers, which are .cmd on Windows
  // and cannot be executed directly. Passing it for everything broke
  // `process.execPath`: the shell re-split the path at the space in
  // "Program Files" and tried to run "C:\Program".
  const needsShell = process.platform === "win32" && (command === "npm" || command === "npx");
  execFileSync(command, args, { cwd: here, stdio: "inherit", shell: needsShell });
}

rmSync(build, { recursive: true, force: true });
mkdirSync(build, { recursive: true });
mkdirSync(release, { recursive: true });

console.log("\nBundling\n");
run("npm", ["run", "build"]);

console.log("\nPreparing the executable\n");
run(process.execPath, ["--experimental-sea-config", "sea-config.json"]);

// A copy of the running Node binary is the host. Copying rather than linking
// so the original is never modified — injecting into the installed node.exe
// would break every other Node program on the machine.
const host = join(build, exeName);
copyFileSync(process.execPath, host);

run("npx", [
  "--yes",
  "postject",
  host.split("\\").join("/"),
  "NODE_SEA_BLOB",
  join(build, "sea-prep.blob").split("\\").join("/"),
  "--sentinel-fuse",
  "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2",
]);

// Proof before packaging. A zip containing an executable that does not start
// is worse than no zip: it fails in a kitchen rather than here.
console.log("\nChecking it runs\n");
const out = execFileSync(host, ["status"], { encoding: "utf8" }).trim();
if (!/Agent|Not paired/.test(out)) {
  throw new Error(`The packaged agent did not answer as expected:\n${out}`);
}
console.log(`  ok (${(statSync(host).size / 1024 / 1024).toFixed(0)}MB)`);

const payload = join(release, `QuickBitePrintAgent-${version}-win-x64`);
rmSync(payload, { recursive: true, force: true });
mkdirSync(payload, { recursive: true });
copyFileSync(host, join(payload, exeName));
for (const file of ["install.ps1", "uninstall.ps1"]) {
  copyFileSync(join(here, "installer", file), join(payload, file));
}
copyFileSync(join(here, "INSTALL.txt"), join(payload, "INSTALL.txt"));

const zip = `${payload}.zip`;
rmSync(zip, { force: true });
// `Compress-Archive` rather than a zip dependency: it is on every supported
// Windows and this script only ever runs on the machine that builds a release.
run("powershell", [
  "-NoProfile",
  "-Command",
  `Compress-Archive -Path '${payload}\*' -DestinationPath '${zip}' -Force`,
]);

if (!existsSync(zip)) throw new Error("Compress-Archive produced nothing");
console.log(`\n  ${zip}`);
console.log(`  ${(statSync(zip).size / 1024 / 1024).toFixed(0)}MB — copy this to any Windows PC.\n`);
