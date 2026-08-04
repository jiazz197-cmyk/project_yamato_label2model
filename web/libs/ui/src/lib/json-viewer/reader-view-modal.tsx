import { type FC, useState, useMemo } from "react";
import sanitizeHtml from "sanitize-html";
import { Markdown } from "../../../../editor/src/components/Markdown/Markdown";
import { Modal } from "../modal";
import { Tabs, TabsList, TabsTrigger } from "../tabs/tabs";
import styles from "./reader-view-modal.module.css";

type ContentFormat = "plain" | "markdown" | "html";

export interface ReaderViewModalProps {
  content: string;
  isOpen: boolean;
  onClose: () => void;
}

/**
 * ReaderViewModal - Full-screen modal for viewing long strings
 *
 * Provides three viewing modes:
 * - Plain Text: Raw text with preserved whitespace
 * - Markdown: Rendered markdown content
 * - HTML: Sanitized HTML content
 */
export const ReaderViewModal: FC<ReaderViewModalProps> = ({ content, isOpen, onClose }) => {
  const [format, setFormat] = useState<ContentFormat>("plain");

  // Sanitize HTML content
  const sanitizedHtml = useMemo(() => {
    if (format !== "html") return "";

    return sanitizeHtml(content, {
      allowedTags: sanitizeHtml.defaults.allowedTags.concat(["img"]),
      allowedAttributes: {
        ...sanitizeHtml.defaults.allowedAttributes,
        "*": ["class", "style"],
      },
    });
  }, [content, format]);

  const renderContent = () => {
    switch (format) {
      case "plain":
        return (
          <pre className={styles.plainText} aria-label="纯文本内容">
            {content}
          </pre>
        );
      case "markdown":
        return (
          <div className={styles.markdownContent} aria-label="Markdown 内容">
            <Markdown text={content} allowHtml={true} />
          </div>
        );
      case "html":
        return (
          <div
            className={styles.htmlContent}
            aria-label="HTML 内容"
            dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
          />
        );
      default:
        return null;
    }
  };

  const headerContent = (
    <Tabs value={format} onValueChange={(v) => setFormat(v as ContentFormat)} variant="default">
      <TabsList>
        <TabsTrigger value="plain">纯文本</TabsTrigger>
        <TabsTrigger value="markdown">Markdown</TabsTrigger>
        <TabsTrigger value="html">HTML</TabsTrigger>
      </TabsList>
    </Tabs>
  );

  return (
    // @ts-expect-error - Modal is a class component with React type compatibility issues
    <Modal
      visible={isOpen}
      onHide={onClose}
      fullscreen={true}
      title="阅读视图"
      header={headerContent}
      allowClose={true}
      closeOnClickOutside={false}
      className={styles.readerViewModal}
      data-testid="reader-view-modal"
    >
      <div className={styles.contentContainer}>{renderContent()}</div>
    </Modal>
  );
};
