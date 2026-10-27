function cyclopsFitTree(container, fit) {
  var nodes = container.querySelectorAll(":scope > .node");
  var svg = container.querySelector(":scope > svg");
  if (!nodes.length) {
    return;
  }
  var minX = Infinity, minY = Infinity, maxX = 0, maxY = 0, i, n;
  for (i = 0; i < nodes.length; i++) {
    n = nodes[i];
    minX = Math.min(minX, n.offsetLeft);
    minY = Math.min(minY, n.offsetTop);
    maxX = Math.max(maxX, n.offsetLeft + n.offsetWidth);
    maxY = Math.max(maxY, n.offsetTop + n.offsetHeight);
  }
  var pad = 14;
  var dx = minX < pad ? pad - minX : 0;
  var dy = minY < pad ? pad - minY : 0;
  if (dx || dy) {
    for (i = 0; i < container.children.length; i++) {
      container.children[i].style.transform = "translate(" + dx + "px, " + dy + "px)";
    }
  }
  var width = maxX + dx + pad;
  var height = maxY + dy + pad;
  if (svg) {
    svg.style.display = "block";
    svg.style.overflow = "visible";
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
  }
  container.style.width = width + "px";
  container.style.height = height + "px";
  var wrap = container.parentElement;
  var zoom = 1;
  if (!fit || fit === "fit") {
    zoom = Math.max(0.45, Math.min(1, ((wrap ? wrap.clientWidth : width) - 4) / width));
  } else {
    zoom = Number(fit) || 1;
  }
  container.style.zoom = zoom;
  var root = container.querySelector("[data-root]");
  var rootNode = root && root.closest ? root.closest(".node") : nodes[0];
  if (wrap && rootNode) {
    wrap.scrollTop = Math.max(0, (rootNode.offsetTop + dy + rootNode.offsetHeight / 2) * zoom - wrap.clientHeight / 2);
    wrap.scrollLeft = 0;
  }
}

function cyclopsMountTree(container, nodeStructure, orientation, fit) {
  if (!container) {
    return;
  }
  if (!window.Treant) {
    container.innerHTML = '<p class="bc-note">The flow chart library did not load.</p>';
    return;
  }
  if (window.__cyTree && window.__cyTree.destroy) {
    try { window.__cyTree.destroy(); } catch (e) {}
    window.__cyTree = null;
  }
  container.innerHTML = "";
  container.style.width = "";
  container.style.height = "";
  container.style.zoom = "1";
  if (!container.id) {
    container.id = "cy-flow-tree";
  }
  var vertical = orientation === "NORTH";
  try {
    window.__cyTree = new Treant({
      chart: {
        container: "#" + container.id,
        rootOrientation: orientation || "EAST",
        nodeAlign: "CENTER",
        scrollbar: "None",
        levelSeparation: vertical ? 34 : 46,
        siblingSeparation: vertical ? 14 : 8,
        subTeeSeparation: vertical ? 22 : 18,
        padding: 14,
        connectors: { type: "step", style: { stroke: "#9aa8bd", "stroke-width": 1.4 } },
        node: { HTMLclass: "cy-tnode" }
      },
      nodeStructure: nodeStructure
    });
    cyclopsFitTree(container, fit);
  } catch (e) {
    container.innerHTML = '<p class="bc-note">The flow chart could not be drawn. The color cards below list the same setups.</p>';
  }
}
