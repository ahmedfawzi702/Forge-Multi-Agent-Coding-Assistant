"use client";
import { Children, isValidElement, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return Children.toArray(node).map(child => typeof child === "string" ? child : isValidElement<{ children?: ReactNode }>(child) ? textOf(child.props.children) : "").join("");
}
function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  return <div className="code-block"><div><span>CODE</span><button aria-label="Copy code block" onClick={async () => { try { await navigator.clipboard.writeText(textOf(children).replace(/\n$/, "")); setCopied(true); setTimeout(() => setCopied(false), 1400); } catch { setCopied(false); } }}>{copied ? <Check size={12} /> : <Copy size={12} />}{copied ? "Copied" : "Copy"}</button></div><pre>{children}</pre></div>;
}

export function MessageRenderer({ content, paths, onSource }: { content: string; paths: string[]; onSource: (path: string, line?: number) => void }) {
  const reference = (value: string): { path: string; line: number } | null => {
    const match = value.trim().match(/^(.+?)(?::|#L)(\d+)(?:[-–]\d+)?$/);
    if (!match) return null;
    const candidate = match[1].replaceAll("\\", "/");
    const found = paths.includes(candidate) ? candidate : paths.filter(p => p.split("/").at(-1) === candidate);
    const path = typeof found === "string" ? found : found.length === 1 ? found[0] : null;
    return path ? { path, line: Number(match[2]) } : null;
  };
  const linkReferences = (children: ReactNode): ReactNode => Children.map(children, child => {
    if (typeof child !== "string") return child;
    return child.split(/((?:[\w.-]+[\\/])*[\w.-]+\.[\w]+(?::|#L)\d+(?:[-–]\d+)?)/g).map((part, index) => {
      const ref = reference(part);
      return ref ? <button key={index} className="source-reference" onClick={() => onSource(ref.path, ref.line)}>{part}</button> : part;
    });
  });
  return <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml components={{ img: () => null,
    p: ({ children }) => <p>{linkReferences(children)}</p>,
    li: ({ children }) => <li>{linkReferences(children)}</li>,
    td: ({ children }) => <td>{linkReferences(children)}</td>,
    pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
    code: ({ children, className }) => { const ref = !className ? reference(textOf(children)) : null; return ref ? <button className="source-reference" onClick={() => onSource(ref.path, ref.line)}>{children}</button> : <code className={className}>{children}</code>; },
    a: ({ href, children }) => { const ref = reference(href || "") || reference(textOf(children)); return ref ? <button className="source-reference" onClick={() => onSource(ref.path, ref.line)}>{children}</button> : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>; },
    table: ({ children }) => <div className="markdown-table"><table>{children}</table></div>,
  }}>{content}</Markdown></div>;
}
