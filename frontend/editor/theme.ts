import type { editor } from "monaco-editor";

export const FORGE_EDITOR_THEME = "forge";

/** Shared by normal editors and diff views, including when a diff opens first. */
export const forgeEditorTheme: editor.IStandaloneThemeData = {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "comment", foreground: "7A7E85", fontStyle: "italic" },
    { token: "keyword", foreground: "CF8E6D" },
    { token: "string", foreground: "6AAB73" },
    { token: "number", foreground: "2AACB8" },
    { token: "type", foreground: "BCBEC4" },
    { token: "type.identifier", foreground: "BCBEC4" },
    { token: "identifier", foreground: "BCBEC4" },
    { token: "delimiter", foreground: "BCBEC4" },
    { token: "tag", foreground: "D5B778" },
    { token: "attribute.name", foreground: "BABABA" },
  ],
  colors: {
    "editor.background": "#1E1E21",
    "editor.foreground": "#BCBEC4",
    "editor.lineHighlightBackground": "#282C2D",
    "editorLineNumber.foreground": "#62666D",
    "editorLineNumber.activeForeground": "#A1A5AD",
    "editorCursor.foreground": "#DFE1E5",
    "editor.selectionBackground": "#2D415F",
    "editor.inactiveSelectionBackground": "#30353C",
    "editor.selectionHighlightBackground": "#35517455",
    "editorGutter.background": "#1E1E21",
    "editorWidget.background": "#2B2E30",
    "editorWidget.border": "#51555B",
    "editorSuggestWidget.background": "#282C2D",
    "editorSuggestWidget.border": "#51555B",
    "editorSuggestWidget.selectedBackground": "#2D415F",
    "editorHoverWidget.background": "#282C2D",
    "editorHoverWidget.border": "#51555B",
    "editorIndentGuide.background1": "#35383C",
    "editorIndentGuide.activeBackground1": "#51555B",
    "focusBorder": "#54AEFF",
    "list.activeSelectionBackground": "#2D415F",
    "scrollbarSlider.background": "#60646C66",
    "scrollbarSlider.hoverBackground": "#757A8388",
    "diffEditor.insertedTextBackground": "#45864A33",
    "diffEditor.removedTextBackground": "#A34B4B33",
  },
};
