import mammoth from "mammoth";

const MAX_FILE_CHARS = 80000; // 单文件 80K 字符兜底（约 16-20 万 token 上限）

export async function parseFile(file: File): Promise<string> {
  const ext = "." + (file.name.split(".").pop()?.toLowerCase() || "");
  try {
    if (ext === ".docx") {
      const arrayBuffer = await file.arrayBuffer();
      const result = await mammoth.extractRawText({ arrayBuffer });
      return (result.value || "").slice(0, MAX_FILE_CHARS);
    }
    const text = await file.text();
    return text.slice(0, MAX_FILE_CHARS);
  } catch (e) {
    console.error(`[parseFile] ${file.name} 解析失败:`, e);
    return "";
  }
}

export async function parseFilesToPrefix(files: File[]): Promise<{ prefix: string }> {
  if (!files.length) return { prefix: "" };
  const parts: string[] = [];
  for (let i = 0; i < files.length; i++) {
    const content = await parseFile(files[i]);
    if (content.trim()) {
      parts.push(`附件${i + 1}内容：${files[i].name}\n${content}`);
    } else {
      parts.push(`附件${i + 1}内容：${files[i].name}\n（解析失败或内容为空）`);
    }
  }
  return { prefix: parts.join("\n\n") + "\n\n" };
}
