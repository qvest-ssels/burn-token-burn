;;; token-finops.el --- Mode-line + buffer for token-finops cache -*- lexical-binding: t; -*-

;; Copyright (C) 2026 the burn-token-burn contributors

;; Author: burn-token-burn contributors
;; Maintainer: burn-token-burn contributors
;; URL: https://github.com/qvest-ssels/burn-token-burn
;; Version: 0.1.0
;; Package-Requires: ((emacs "26.1"))
;; Keywords: tools, convenience

;; This file is not part of GNU Emacs.

;; This program is free software; you can redistribute it and/or modify
;; it under the terms of the GNU General Public License as published by
;; the Free Software Foundation, either version 3 of the License, or
;; (at your option) any later version.

;;; Commentary:

;; token-finops.el is the Emacs integration for `token-finops-cli'
;; (https://github.com/qvest-ssels/burn-token-burn), a read-only tracker of
;; budget "runway" for coding assistants that leave telemetry on disk
;; (GitHub Copilot, Claude Code, Codex, Gemini CLI, ...).
;;
;; This package is READ-ONLY against the cache file.  It never invokes the
;; `token-finops' binary and never triggers a rescan.  It only reads
;; whatever `~/.token-finops/last.json' last contained, on the same
;; "one shared cache, many dumb readers" contract documented at the top of
;; `token-finops-cli/src/token_finops_cli/status.py' and already used by
;; the tmux integration in `contrib/tmux/'.  Keep the cache warm with the
;; refresher timer in `contrib/refresh/' (cron/systemd/launchd) -- this
;; package will pick up whatever that timer last wrote.
;;
;; Cache contract (see `status.py'):
;;
;;   { "schema_version": 1,
;;     "generated_at": "<ISO-8601 UTC>",
;;     "tools": [ { "tool": "claude_code", "display_name": "Claude Code",
;;                  "window": "5h", "runway_days": 0.08,
;;                  "used_fraction": 0.61, "status": "WARN" }, ... ],
;;     "binding": { "tool": ..., "display_name": ..., "runway_days": ...,
;;                  "used_fraction": ..., "status": ... } | null }
;;
;; Usage:
;;
;;   (require 'token-finops)
;;   (token-finops-mode 1)          ; mode-line segment, refreshed on a timer
;;   M-x token-finops-show          ; full per-tool table in a dedicated buffer
;;
;; See README.md in this directory for `use-package' recipes.

;;; Code:

(require 'json)
(require 'tabulated-list)
(require 'cl-lib)

(defgroup token-finops nil
  "Mode-line segment and buffer for the token-finops budget cache."
  :group 'tools
  :prefix "token-finops-")

(defcustom token-finops-cache-file
  (expand-file-name "~/.token-finops/last.json")
  "Path to the token-finops status cache written by `token-finops status'.

This package only ever reads this file.  It is refreshed by the user's
own cron/systemd-timer/launchd job (see `contrib/refresh/' in the
burn-token-burn repository) -- token-finops.el never shells out to the
`token-finops' binary itself."
  :type 'file
  :group 'token-finops)

(defcustom token-finops-schema-version 1
  "Expected `schema_version' of the cache file.

A mismatch (an old package talking to a newer CLI, or vice versa) is
treated the same as a missing/corrupt cache: shown as \"no data\",
never signalled as an error."
  :type 'integer
  :group 'token-finops)

(defcustom token-finops-mode-line-interval 45
  "Seconds between mode-line refreshes.

Refreshing only re-reads `token-finops-cache-file' from disk; it never
invokes `token-finops' itself."
  :type 'integer
  :group 'token-finops)

(defcustom token-finops-mode-line-prefix "TF:"
  "String prepended to the mode-line segment."
  :type 'string
  :group 'token-finops)

(defface token-finops-ok-face '((t :inherit success))
  "Face for an OK/UNLIMITED status in the mode-line and buffer."
  :group 'token-finops)

(defface token-finops-warn-face '((t :inherit warning))
  "Face for a WARN status in the mode-line and buffer."
  :group 'token-finops)

(defface token-finops-critical-face '((t :inherit error))
  "Face for a CRITICAL/EXHAUSTED status in the mode-line and buffer."
  :group 'token-finops)

(defface token-finops-unknown-face '((t :inherit shadow))
  "Face for an UNKNOWN status, or when no data is available."
  :group 'token-finops)

(defconst token-finops--short-names
  '(("copilot" . "CP") ("claude_code" . "CC") ("codex" . "CX")
    ("gemini_cli" . "GM") ("hermes" . "HM") ("opencode" . "OC")
    ("cline" . "CL") ("aider" . "AI") ("continue_dev" . "CT")
    ("continue" . "CT"))
  "Mirrors `SHORT' in token-finops-cli's status.py, for the terse mode-line.")

(defconst token-finops--glyphs
  '(("OK" . "") ("WARN" . "!") ("CRITICAL" . "!!") ("EXHAUSTED" . "X")
    ("UNLIMITED" . "") ("UNKNOWN" . "?"))
  "Mirrors `GLYPH' in status.py.")

(defvar token-finops-mode-line-string ""
  "Current mode-line segment.  Updated by `token-finops--refresh'.")
;;;###autoload
(put 'token-finops-mode-line-string 'risky-local-variable t)

(defvar token-finops--timer nil
  "The `run-with-timer' handle refreshing the mode-line, or nil.")

(defconst token-finops--no-data-message
  "token-finops: no data yet -- run `token-finops status' first"
  "Shown in the mode-line and buffer when the cache is missing/corrupt/stale.")

;;; --------------------------------------------------------------------
;;; Cache reading -- read-only, never signals
;;; --------------------------------------------------------------------

(defun token-finops--read-cache ()
  "Read and parse `token-finops-cache-file'.

Returns the parsed JSON as a nested alist/vector structure (per
`json-read-file's default `json-object-type' of `alist' and
`json-array-type' of `vector'), or nil if the file is missing, is not
valid JSON, or its `schema_version' does not match
`token-finops-schema-version'.  Never signals an error -- this must be
safe to call from a mode-line timer without ever disrupting the user's
Emacs session."
  (condition-case nil
      (when (file-readable-p token-finops-cache-file)
        (let* ((json-object-type 'alist)
               (json-array-type 'vector)
               (json-key-type 'symbol)
               (snapshot (json-read-file token-finops-cache-file)))
          (when (and (listp snapshot)
                     (eql (alist-get 'schema_version snapshot)
                          token-finops-schema-version))
            snapshot)))
    (error nil)))

(defun token-finops--short (tool)
  "Short 2-letter code for TOOL (a string), or its first two letters upcased."
  (or (cdr (assoc tool token-finops--short-names))
      (upcase (substring tool 0 (min 2 (length tool))))))

(defun token-finops--glyph (status)
  "Terse flag character(s) for STATUS, mirroring status.py's GLYPH table."
  (or (cdr (assoc status token-finops--glyphs)) ""))

(defun token-finops--face-for-status (status)
  "Return the face to use for STATUS."
  (cond
   ((member status '("OK" "UNLIMITED")) 'token-finops-ok-face)
   ((equal status "WARN") 'token-finops-warn-face)
   ((member status '("CRITICAL" "EXHAUSTED")) 'token-finops-critical-face)
   (t 'token-finops-unknown-face)))

(defun token-finops--fmt-pct (fraction)
  "Format FRACTION (0..1 or nil) as a percentage string, mirroring `pct'."
  (if (numberp fraction)
      (format "%d%%" (round (* fraction 100)))
    "?"))

(defun token-finops--fmt-runway (days status)
  "Format runway DAYS given tool STATUS, mirroring `_runway_of' in status.py.

A null runway on an OK tool means \"no burn yet\" (unbounded), not
unknown."
  (cond
   ((and (null days) (equal status "OK")) "inf")
   ((null days) "n/a")
   ((and (floatp days) (or (isnan days) (= days 1.0e+INF))) "inf")
   ((< days 1) (format "%.0fh" (* days 24)))
   (t (format "%.0fd" days))))

;;; --------------------------------------------------------------------
;;; Mode-line segment
;;; --------------------------------------------------------------------

(defun token-finops--binding-segment (snapshot)
  "Build the terse mode-line string from SNAPSHOT's binding constraint."
  (let ((binding (alist-get 'binding snapshot)))
    (if (or (null binding) (eq binding :null) (eq binding 'null))
        (let ((tools (alist-get 'tools snapshot)))
          (if (and tools (> (length tools) 0))
              ;; No binding tool (e.g. everything UNLIMITED) but we do have
              ;; data: say so tersely rather than claiming "no data".
              "no active budget"
            token-finops--no-data-message))
      (let* ((tool (format "%s" (alist-get 'tool binding)))
             (status (format "%s" (alist-get 'status binding)))
             (runway (token-finops--fmt-runway (alist-get 'runway_days binding) status))
             (used (token-finops--fmt-pct (alist-get 'used_fraction binding))))
        (format "%s %s %s%s"
                (token-finops--short tool) used runway
                (token-finops--glyph status))))))

(defun token-finops--refresh ()
  "Re-read the cache file and update `token-finops-mode-line-string'.

Never shells out to `token-finops' -- this only reads whatever is
already on disk.  Never signals: any failure degrades to the
\"no data\" message."
  (let* ((snapshot (token-finops--read-cache))
         (text (if snapshot
                   (token-finops--binding-segment snapshot)
                 token-finops--no-data-message)))
    (setq token-finops-mode-line-string
          (concat " " token-finops-mode-line-prefix text " "))
    (when (get-buffer "*token-finops*")
      (with-current-buffer "*token-finops*"
        (when (derived-mode-p 'token-finops-mode)
          (token-finops--populate-buffer))))
    (force-mode-line-update t)))

;;;###autoload
(define-minor-mode token-finops-mode
  "Toggle the token-finops mode-line segment.

Shows the binding-constraint tool's short name, used percentage,
runway and status flag (e.g. \"CC 61% 2h!\"), refreshed every
`token-finops-mode-line-interval' seconds by re-reading
`token-finops-cache-file'.  This never invokes the `token-finops'
binary; run it yourself (or via cron/systemd-timer/launchd, see
`contrib/refresh/' in burn-token-burn) to keep the cache warm."
  :global t
  :group 'token-finops
  (if token-finops-mode
      (progn
        (unless (memq 'token-finops-mode-line-string global-mode-string)
          (setq global-mode-string
                (append (or global-mode-string '(""))
                        '(token-finops-mode-line-string))))
        (token-finops--refresh)
        (when token-finops--timer
          (cancel-timer token-finops--timer))
        (setq token-finops--timer
              (run-with-timer token-finops-mode-line-interval
                               token-finops-mode-line-interval
                               #'token-finops--refresh)))
    (when token-finops--timer
      (cancel-timer token-finops--timer)
      (setq token-finops--timer nil))
    (setq global-mode-string
          (delq 'token-finops-mode-line-string global-mode-string))
    (setq token-finops-mode-line-string "")))

;;; --------------------------------------------------------------------
;;; Transient buffer: full per-tool table
;;; --------------------------------------------------------------------

(defvar token-finops-buffer-name "*token-finops*"
  "Name of the buffer used by `token-finops-show'.")

(defun token-finops--tools-entries (snapshot)
  "Build `tabulated-list-entries' from SNAPSHOT."
  (let ((tools (append (alist-get 'tools snapshot) nil)))
    (mapcar
     (lambda (tool)
       (let* ((name (format "%s" (or (alist-get 'display_name tool)
                                      (alist-get 'tool tool))))
              (status (format "%s" (alist-get 'status tool)))
              (used (token-finops--fmt-pct (alist-get 'used_fraction tool)))
              (window (format "%s" (or (alist-get 'window tool) "-")))
              (runway (token-finops--fmt-runway (alist-get 'runway_days tool) status))
              (face (token-finops--face-for-status status)))
         (list (alist-get 'tool tool)
               (vector name window used runway
                       (propertize status 'face face)))))
     tools)))

(define-derived-mode token-finops-list-mode tabulated-list-mode "TokenFinops"
  "Major mode for the token-finops per-tool status buffer."
  (setq tabulated-list-format
        [("Tool" 16 t) ("Window" 8 t) ("Used" 6 t) ("Runway" 8 t) ("Status" 10 t)]
        tabulated-list-padding 2
        tabulated-list-sort-key (cons "Tool" nil))
  (tabulated-list-init-header)
  (local-set-key "g" #'token-finops-refresh-buffer))

(defun token-finops--populate-buffer ()
  "Fill the current `token-finops-list-mode' buffer from the cache file."
  (let ((snapshot (token-finops--read-cache))
        (inhibit-read-only t))
    (if (null snapshot)
        (progn
          (setq tabulated-list-entries nil)
          (tabulated-list-print t)
          (goto-char (point-max))
          (insert "\n" token-finops--no-data-message "\n"))
      (let ((binding (alist-get 'binding snapshot))
            (generated (alist-get 'generated_at snapshot)))
        (setq tabulated-list-entries (token-finops--tools-entries snapshot))
        (tabulated-list-print t)
        (goto-char (point-max))
        (insert "\n")
        (insert (format "generated at: %s\n" (or generated "unknown")))
        (if (or (null binding) (eq binding :null) (eq binding 'null))
            (insert "binding constraint: none\n")
          (insert (format "binding constraint: %s (%s, runway %s)\n"
                          (alist-get 'display_name binding)
                          (alist-get 'status binding)
                          (token-finops--fmt-runway
                           (alist-get 'runway_days binding)
                           (format "%s" (alist-get 'status binding))))))
        (insert "\nPress `g' to refresh (re-reads the cache file; never rescans).\n")))))

;;;###autoload
(defun token-finops-show ()
  "Open the `*token-finops*' buffer with the full per-tool status table.

Reads `token-finops-cache-file' once; never invokes `token-finops'
itself.  If the cache is missing, corrupt or has a mismatched
`schema_version', shows a clear \"no data yet\" message instead of
signalling an error."
  (interactive)
  (let ((buf (get-buffer-create token-finops-buffer-name)))
    (with-current-buffer buf
      (unless (derived-mode-p 'token-finops-list-mode)
        (token-finops-list-mode))
      (token-finops--populate-buffer))
    (pop-to-buffer buf)))

(defun token-finops-refresh-buffer ()
  "Refresh the `*token-finops*' buffer in place, and the mode-line segment."
  (interactive)
  (token-finops--refresh)
  (when (derived-mode-p 'token-finops-list-mode)
    (token-finops--populate-buffer)))

;;;###autoload
(defalias 'token-finops 'token-finops-show
  "Alias for `token-finops-show', matching the `M-x token-finops' style
mentioned in docs/INTEGRATIONS.md.")

(provide 'token-finops)

;;; token-finops.el ends here
