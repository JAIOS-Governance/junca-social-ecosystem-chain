import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const png = await readFile(join(root, "snapshot", "icon-512.png"));
const encoded = png.toString("base64");
const svg = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512" role="img" aria-label="Official JUNCA symbol">
  <metadata>Official JUNCA symbol derived without redrawing from Drive master package 1DiGrLHOWRcrVnt2BdijSFDy3U4mSvgBn.</metadata>
  <image
    x="0"
    y="0"
    width="512"
    height="512"
    preserveAspectRatio="xMidYMid meet"
    data-symbol="JUNCA Official Symbol"
    data-rendering="non-distorting-resize"
    data-source-drive-id="1DiGrLHOWRcrVnt2BdijSFDy3U4mSvgBn"
    data-source-package-sha256="3dc49cf3e5110207f4a1274e972d194943aaac8df657caa969cc4e326ecceba9"
    data-source-symbol-sha256="6cba53b6217543d9d4fb33a1d4727ea24ee3dfd09a55ac9ed46da46ff13886cb"
    href="data:image/png;base64,${encoded}"
    xlink:href="data:image/png;base64,${encoded}"
    aria-hidden="true"
  />
</svg>
`;

await Promise.all([
  writeFile(join(root, "snapshot", "favicon.svg"), svg, "utf8"),
  writeFile(join(root, "src", "favicon.svg"), svg, "utf8"),
]);

console.log("Wrote official JUNCA symbol favicon assets");
