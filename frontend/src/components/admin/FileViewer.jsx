import { useEffect, useId, useRef } from "react";
import { ExternalLink, FileText, Image, X } from "lucide-react";
import { formatFileSize } from "../../services/businessForm";
import "../../styles/settings.css";

export default function FileViewer({ title, file, onClose }) {
  const dialogRef = useRef(null);
  const backdropPointerRef = useRef(false);
  const titleId = useId();
  const isImage = file.type.startsWith("image/");
  const Icon = isImage ? Image : FileText;

  useEffect(() => {
    const dialog = dialogRef.current;
    const trigger = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog admin-viewer"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onPointerDown={(event) => {
        backdropPointerRef.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (backdropPointerRef.current && event.target === event.currentTarget) onClose();
        backdropPointerRef.current = false;
      }}
    >
      <header className="admin-viewer-head">
        <span className="admin-file-icon" aria-hidden="true"><Icon /></span>
        <div className="admin-viewer-title">
          <h2 id={titleId}>{title}</h2>
          <p>{file.name} · {formatFileSize(file.size)}</p>
        </div>
        {file.url && (
          <a className="admin-btn admin-btn-outline admin-btn-small" href={file.url} target="_blank" rel="noreferrer">
            <ExternalLink aria-hidden="true" /> Open in new tab
          </a>
        )}
        <button type="button" className="admin-viewer-close" onClick={onClose} aria-label="Close">
          <X aria-hidden="true" />
        </button>
      </header>

      <div className={`admin-viewer-body${isImage ? " is-image" : ""}`}>
        {!file.url ? (
          <p className="admin-viewer-empty">This file isn't available to preview.</p>
        ) : isImage ? (
          <img src={file.url} alt={`${title}: ${file.name}`} />
        ) : (
          <iframe src={file.url} title={`${title}: ${file.name}`} />
        )}
      </div>
    </dialog>
  );
}
