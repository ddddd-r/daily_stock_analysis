/**
 * 显示层简繁转换(简体 → 繁体/香港标准)。
 *
 * 设计理念:
 *   应用内大量中文为硬编码简体,且部分中文字符串是「逻辑比对用的枚举值」
 *   (如 买入 / 看多 / 数据不可用),后端也以简体下发。直接改源码会破坏比对逻辑。
 *   因此只在「显示层」把渲染到 DOM 的中文即时转成繁体——JS 内部逻辑仍使用简体,
 *   不受影响。用户(香港)看到的全部是繁体。
 *
 * 覆盖范围:文本节点 + 常见可见属性(placeholder / title / aria-label / alt)。
 * 跳过:<input>/<textarea> 的用户输入值、contenteditable、script/style/code/pre。
 */
import * as OpenCC from 'opencc-js';

// cn(简体) → hk(香港繁体标准)
const convert = OpenCC.Converter({ from: 'cn', to: 'hk' });

const CJK = /[㐀-鿿]/;
const WATCH_ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE', 'NOSCRIPT']);

function convertTextNode(node: Text): void {
  const val = node.nodeValue;
  if (!val || !CJK.test(val)) return;
  const next = convert(val);
  if (next !== val) node.nodeValue = next; // 仅在变化时写入,避免无限触发
}

function convertElementAttrs(el: Element): void {
  for (const attr of WATCH_ATTRS) {
    const val = el.getAttribute(attr);
    if (!val || !CJK.test(val)) continue;
    const next = convert(val);
    if (next !== val) el.setAttribute(attr, next);
  }
}

function shouldSkip(el: Element): boolean {
  return SKIP_TAGS.has(el.tagName) || (el as HTMLElement).isContentEditable === true;
}

/** 递归处理一个节点及其子树。 */
function processNode(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    convertTextNode(node as Text);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const el = node as Element;
  if (shouldSkip(el)) return;
  convertElementAttrs(el);
  for (let i = 0; i < node.childNodes.length; i++) {
    processNode(node.childNodes[i]);
  }
}

let started = false;

/** 启动全局显示层简繁转换。幂等:重复调用无副作用。 */
export function startTraditionalize(): void {
  if (started || typeof document === 'undefined') return;
  started = true;

  // 文档标题
  if (document.title && CJK.test(document.title)) {
    document.title = convert(document.title);
  }

  // 首次全量转换
  if (document.body) processNode(document.body);

  // 增量监听后续变化(React 重渲染、路由切换、异步内容等)
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'characterData') {
        convertTextNode(m.target as Text);
      } else if (m.type === 'attributes' && m.target.nodeType === Node.ELEMENT_NODE) {
        convertElementAttrs(m.target as Element);
      } else if (m.type === 'childList') {
        m.addedNodes.forEach(processNode);
      }
    }
  });

  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: WATCH_ATTRS,
  });
}
