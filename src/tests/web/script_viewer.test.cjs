const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class TextNode {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ""; }
  set textContent(value) { this.value = value; this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(""); }
  set innerHTML(_) { throw new Error("Script content must not become HTML"); }
  appendChild(child) { this.children.push(child); }
  replaceChildren(fragment) { this.value = ""; this.children = fragment.children; }
}
const document = {
  createElement: tag => new TextNode(tag),
  createDocumentFragment: () => new TextNode("fragment"),
};
const context = {window: {}, document};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../web/script-viewer.js"), "utf8"), context);
const viewer = context.window.PolarisScriptViewer;
const scripts = path.join(__dirname, "../../scripts");
const names = ["disk_cleanup.sh", "kill_target_process.sh", "verify_disk.sh", "verify_cpu.sh", "verify_service.sh"];

test("all standard scripts preserve every character with and without colors", () => {
  for (const name of names) {
    const source = fs.readFileSync(path.join(scripts, name), "utf8");
    const element = new TextNode("pre");
    viewer.renderScript(element, source, true);
    assert.equal(element.textContent, source);
    assert.ok(element.children.length > 0);
    viewer.renderScript(element, source, false);
    assert.equal(element.textContent, source);
    assert.equal(element.children.length, 0);
    assert.notEqual(viewer.describeScript(name).title, "Script do catálogo");
  }
});

test("HTML-shaped content is literal text, never executable markup", () => {
  const source = '# <img src=x onerror="alert(1)">\r\necho "<script>boom</script>"\n';
  const element = new TextNode("pre");
  viewer.renderScript(element, source, true);
  assert.equal(element.textContent, source);
  assert.ok(element.children.every(child => child.tag === "span"));
});

test("unknown and prototype names never receive a standard script description", () => {
  for (const name of ["other.sh", "__proto__", "constructor"]) {
    assert.equal(viewer.describeScript(name).title, "Script do catálogo");
    assert.match(viewer.describeScript(name).effect, /não presuma/);
  }
  assert.match(viewer.describeScript("disk_cleanup.sh").purpose, /independentemente da idade/);
  assert.match(viewer.describeScript("disk_cleanup.sh").effect, /Não há restauração/);
});

test("empty and unusual source is not truncated by the lexer", () => {
  for (const source of ["", "echo 'unterminated", "\tλ=$X\r\n", "echo 😀", "foo#bar\n"]) {
    assert.equal(viewer.tokenizeShell(source).map(token => token.text).join(""), source);
  }
});
