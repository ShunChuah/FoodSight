import { useState } from "react";
import { Sparkles, Volume2 } from "lucide-react";
import "../../styles/chat.css";

function formatInlineText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);

  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    }

    return part;
  });
}

function cleanPointTitle(title) {
  return title.replace(/\*\*/g, "").trim();
}

function parseAnswer(answer) {
  if (!answer) return [];

  const normalized = answer.replace(/\r\n/g, "\n").trim();
  const recommendationPattern = /(?:^|\n)\s*(\d+)\.\s+([\s\S]*?)(?=\n\s*\d+\.|$)/g;
  const recommendations = [];
  let match;

  while ((match = recommendationPattern.exec(normalized)) !== null) {
    const itemText = match[2].trim();
    const bulletExplanationMatch = itemText.match(
      /^(.+?)\s*\n\s*[-*]\s+([\s\S]+)$/,
    );
    const boldTitleMatch = itemText.match(/^\*\*([^*]+)\*\*:?\s*([\s\S]*)$/);
    const parenthesizedMatch = itemText.match(/^(.+?)\s*\(([\s\S]+)\)$/);

    if (bulletExplanationMatch) {
      recommendations.push({
        number: match[1],
        title: cleanPointTitle(bulletExplanationMatch[1]),
        description: bulletExplanationMatch[2].trim(),
      });
      continue;
    }

    if (boldTitleMatch) {
      recommendations.push({
        number: match[1],
        title: cleanPointTitle(boldTitleMatch[1]),
        description: boldTitleMatch[2].trim(),
      });
      continue;
    }

    if (parenthesizedMatch) {
      recommendations.push({
        number: match[1],
        title: cleanPointTitle(parenthesizedMatch[1]),
        description: parenthesizedMatch[2].trim(),
      });
      continue;
    }

    recommendations.push({
      number: match[1],
      title: cleanPointTitle(itemText),
      description: "",
    });
  }

  const intro = normalized.split(/\n?\s*1\.\s+/)[0].trim();
  const sectionSource = normalized.slice(recommendationPattern.lastIndex || 0);
  const sectionPattern = /\*\*([^*]+):\*\*\s*([\s\S]*?)(?=\n\s*\*\*[^*]+:\*\*|$)/g;
  const sections = [];

  while ((match = sectionPattern.exec(sectionSource)) !== null) {
    sections.push({
      title: match[1].trim(),
      body: match[2].trim(),
    });
  }

  if (!recommendations.length && !sections.length) {
    return [{ type: "paragraph", text: normalized }];
  }

  return [
    ...(intro ? [{ type: "paragraph", text: intro }] : []),
    ...recommendations.map((item) => ({ type: "recommendation", ...item })),
    ...sections.map((section) => ({ type: "section", ...section })),
  ];
}

function FormattedAnswer({ answer }) {
  const blocks = parseAnswer(answer);

  return (
    <div className="ai-response-content">
      {blocks.map((block, index) => {
        if (block.type === "recommendation") {
          return (
            <article className="ai-recommendation" key={`${block.title}-${index}`}>
              <span className="ai-recommendation-number">{block.number}</span>
              <div>
                <h3>{block.title}</h3>
                {block.description && <p>{formatInlineText(block.description)}</p>}
              </div>
            </article>
          );
        }

        if (block.type === "section") {
          return (
            <section className="ai-response-section" key={`${block.title}-${index}`}>
              <h3>{block.title}</h3>
              <p>{formatInlineText(block.body)}</p>
            </section>
          );
        }

        return (
          <p className="ai-response-summary" key={`paragraph-${index}`}>
            {formatInlineText(block.text)}
          </p>
        );
      })}
    </div>
  );
}

function AIResponseCard({
  answer,
  onShowExplanation,
  isExplanationOpen = false,
}) {
  const [selectedAction, setSelectedAction] = useState(null);

  return (
    <div className="ai-response-card">
      <FormattedAnswer answer={answer} />

      <div className="response-actions">
        <button
          className="show-explanation-action"
          type="button"
          title="View Details"
          disabled={isExplanationOpen}
          onClick={() => onShowExplanation && onShowExplanation()}
        >
          <Sparkles />
          <span>View Details</span>
        </button>

        <button
          className={`speak-action ${selectedAction === "speak" ? "selected" : ""}`}
          type="button"
          title="Speak Answer"
          onClick={() =>
            setSelectedAction(selectedAction === "speak" ? null : "speak")
          }
        >
          <Volume2 />
          <span>Speak Answer</span>
        </button>
      </div>
    </div>
  );
}

export default AIResponseCard;
