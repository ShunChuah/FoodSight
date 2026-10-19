export function parseAnswer(answer) {
  if (!answer) return [];

  const blocks = [];
  let paragraph = [];
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join("\n") });
      paragraph = [];
    }
  };

  for (const line of answer.replace(/\r\n/g, "\n").trim().split("\n")) {
    if (!line.trim()) {
      flushParagraph();
      continue;
    }
    const numbered = line.match(/^\s*(\d+)[.)]\s+(.+)$/);
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      const previous = blocks.at(-1);
      if (previous?.type === "bullets") previous.items.push(bullet[1]);
      else blocks.push({ type: "bullets", items: [bullet[1]] });
      continue;
    }
    if (numbered) {
      flushParagraph();
      const number = Number(numbered[1]);
      const previous = blocks.at(-1);
      if (
        previous?.type === "list" &&
        number === previous.start + previous.items.length
      ) {
        previous.items.push(numbered[2]);
      } else {
        blocks.push({ type: "list", start: number, items: [numbered[2]] });
      }
      continue;
    }
    const previous = blocks.at(-1);
    if (["list", "bullets"].includes(previous?.type) && /^\s{2,}\S/.test(line)) {
      previous.items[previous.items.length - 1] += `\n${line.trim()}`;
    } else {
      paragraph.push(line);
    }
  }
  flushParagraph();
  return blocks;
}
