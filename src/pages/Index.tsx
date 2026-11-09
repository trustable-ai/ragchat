import { useState, useEffect, useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { toast } from "sonner";
import { marked } from "marked";
import {
  Upload,
  X,
  FileText,
  Settings,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  ChevronDown,
  ArrowUp,
  Square,
  RotateCcw,
} from "lucide-react";

// Configure marked
marked.setOptions({ gfm: true, breaks: true });

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

type PipelineStep = "upload" | "extract" | "cleaning" | "chunking" | "store";

interface FileEntry {
  file: File;
  name: string;
  size: number;
}

interface StepStatus {
  state: "pending" | "running" | "done" | "error";
  label?: string;
}

interface PipelineResult {
  extractedText?: string;
  cleanedText?: string;
  chunks?: string[];
  numChunks?: number;
  numStored?: number;
  docId?: string;
}

interface IndexedDoc {
  doc_id: string;
  filename: string;
  num_chunks: number;
}

interface Source {
  filename: string;
  categoria: string;
  score: number;
}

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

interface DocInfo {
  filename: string;
  chunks: number;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STEPS: PipelineStep[] = ["upload", "extract", "cleaning", "chunking", "store"];
const STEP_LABELS: Record<PipelineStep, string> = {
  upload: "Upload",
  extract: "Extract",
  cleaning: "Cleaning",
  chunking: "Chunking",
  store: "Store",
};

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

const Index = () => {
  // Tab state
  const [activeTab, setActiveTab] = useState<"ingest" | "chat">("ingest");

  // Shared category state
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>("");

  // ---------- Ingest state ----------
  const [showManage, setShowManage] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [editingCat, setEditingCat] = useState<string | null>(null);
  const [editCatName, setEditCatName] = useState("");
  const [catLoading, setCatLoading] = useState(false);

  // File upload
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Pipeline
  const [processing, setProcessing] = useState(false);
  const [currentFileIdx, setCurrentFileIdx] = useState(-1);
  const [stepStatuses, setStepStatuses] = useState<Record<PipelineStep, StepStatus>>(
    () => Object.fromEntries(STEPS.map((s) => [s, { state: "pending" as const }])) as Record<PipelineStep, StepStatus>
  );
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);

  // Indexed documents (ingest tab)
  const [indexedDocs, setIndexedDocs] = useState<IndexedDoc[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);

  // Result accordion
  const [resultAccordion, setResultAccordion] = useState<string>("");

  // ---------- Chat state ----------
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [chatCategory, setChatCategory] = useState("All");
  const [chatDocuments, setChatDocuments] = useState<DocInfo[]>([]);
  const [suggestedQuestions, setSuggestedQuestions] = useState<{ question: string; filename: string }[]>([]);
  const [questionsLoading, setQuestionsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  /* ================================================================ */
  /*  Shared: Category API                                            */
  /* ================================================================ */

  const fetchCategories = useCallback(async () => {
    try {
      const res = await fetch("/api/my/rag/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "list" }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      const list: string[] = Array.isArray(data.categories) ? data.categories : [];
      setCategories(list);
    } catch (e: any) {
      toast.error("Failed to load categories: " + (e.message || e));
    }
  }, []);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  const addCategory = async () => {
    const name = newCatName.trim();
    if (!name) return;
    setCatLoading(true);
    try {
      const res = await fetch("/api/my/rag/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "add", name }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      toast.success(`Category "${name}" added`);
      setNewCatName("");
      await fetchCategories();
    } catch (e: any) {
      toast.error(e.message || "Failed to add category");
    } finally {
      setCatLoading(false);
    }
  };

  const deleteCategory = async (name: string) => {
    setCatLoading(true);
    try {
      const res = await fetch("/api/my/rag/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", name }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      toast.success(`Category "${name}" deleted`);
      if (selectedCategory === name) setSelectedCategory("");
      await fetchCategories();
    } catch (e: any) {
      toast.error(e.message || "Failed to delete category");
    } finally {
      setCatLoading(false);
    }
  };

  const renameCategory = async (oldName: string) => {
    const newName = editCatName.trim();
    if (!newName || newName === oldName) {
      setEditingCat(null);
      return;
    }
    setCatLoading(true);
    try {
      const res = await fetch("/api/my/rag/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "rename", name: oldName, new_name: newName }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      toast.success(`Category renamed to "${newName}"`);
      if (selectedCategory === oldName) setSelectedCategory(newName);
      setEditingCat(null);
      await fetchCategories();
    } catch (e: any) {
      toast.error(e.message || "Failed to rename category");
    } finally {
      setCatLoading(false);
    }
  };

  /* ================================================================ */
  /*  Ingest: Indexed documents                                       */
  /* ================================================================ */

  const fetchIndexedDocs = useCallback(async (cat: string) => {
    // cat === "" means "All"; the backend returns every document when
    // categoria is empty, so we still need to fetch.
    setDocsLoading(true);
    try {
      const res = await fetch("/api/my/rag/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categoria: cat }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setIndexedDocs(Array.isArray(data.documents) ? data.documents : []);
    } catch (e: any) {
      toast.error("Failed to load documents: " + (e.message || e));
      setIndexedDocs([]);
    } finally {
      setDocsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIndexedDocs(selectedCategory);
  }, [selectedCategory, fetchIndexedDocs]);

  const deleteDoc = async (doc: IndexedDoc) => {
    try {
      const res = await fetch("/api/my/rag/delete-doc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: doc.doc_id, filename: doc.filename }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      toast.success(`Deleted "${doc.filename}"`);
      await fetchIndexedDocs(selectedCategory);
    } catch (e: any) {
      toast.error(e.message || "Failed to delete document");
    }
  };

  /* ================================================================ */
  /*  Ingest: File handling                                           */
  /* ================================================================ */

  const addFiles = (incoming: FileList | File[]) => {
    const pdfs = Array.from(incoming).filter((f) => f.type === "application/pdf");
    if (pdfs.length === 0) {
      toast.error("Only PDF files are accepted");
      return;
    }
    const entries: FileEntry[] = pdfs.map((f) => ({ file: f, name: f.name, size: f.size }));
    setFiles((prev) => [...prev, ...entries]);
  };

  const removeFile = (idx: number) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  };

  /* ================================================================ */
  /*  Ingest: Pipeline                                                */
  /* ================================================================ */

  const resetSteps = () =>
    setStepStatuses(
      Object.fromEntries(STEPS.map((s) => [s, { state: "pending" as const }])) as Record<PipelineStep, StepStatus>
    );

  const setStep = (step: PipelineStep, status: StepStatus) =>
    setStepStatuses((prev) => ({ ...prev, [step]: status }));

  const runUpload = async (file: File) => {
    const uuid = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    const baseKey = `uploads/${uuid}/${file.name}`;
    const partKeys: string[] = [];
    const arrayBuffer = await file.arrayBuffer();
    const bytes = new Uint8Array(arrayBuffer);
    const PART_SIZE = 700 * 1024;
    let partNumber = 1;

    for (let offset = 0; offset < bytes.length; offset += PART_SIZE) {
      const chunk = bytes.slice(offset, Math.min(offset + PART_SIZE, bytes.length));
      const partKey = `${baseKey}.part${partNumber}`;
      let binary = "";
      for (let i = 0; i < chunk.length; i++) binary += String.fromCharCode(chunk[i]);
      const b64 = btoa(binary);

      const res = await fetch("/api/my/rag/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: partKey, part: b64 }),
      });
      if (!res.ok) throw new Error(`Upload chunk ${partNumber} failed: ${res.status}`);
      const d = await res.json();
      if (d.error) throw new Error(d.error);
      partKeys.push(partKey);
      partNumber++;
    }
    return { baseKey, partKeys };
  };

  const processFile = async (entry: FileEntry): Promise<PipelineResult> => {
    resetSteps();
    const result: PipelineResult = {};

    // 1. Upload
    setStep("upload", { state: "running" });
    const { baseKey, partKeys } = await runUpload(entry.file);
    setStep("upload", { state: "done" });

    // 2. Extract
    setStep("extract", { state: "running" });
    const extractRes = await fetch("/api/my/rag/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: baseKey, parts: partKeys }),
    });
    if (!extractRes.ok) throw new Error(`Extract failed: ${extractRes.status}`);
    const extractData = await extractRes.json();
    if (extractData.error) throw new Error(extractData.error);
    result.extractedText = extractData.output;
    setStep("extract", { state: "done" });

    // 3. Clean
    setStep("cleaning", { state: "running" });
    const cleanRes = await fetch("/api/my/rag/clean", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: result.extractedText }),
    });
    if (!cleanRes.ok) throw new Error(`Cleaning failed: ${cleanRes.status}`);
    const cleanData = await cleanRes.json();
    if (cleanData.error) throw new Error(cleanData.error);
    result.cleanedText = cleanData.output;
    setStep("cleaning", { state: "done" });

    // 4. Chunk
    setStep("chunking", { state: "running" });
    const chunkRes = await fetch("/api/my/rag/chunk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: result.cleanedText, filename: entry.name, categoria: selectedCategory }),
    });
    if (!chunkRes.ok) throw new Error(`Chunking failed: ${chunkRes.status}`);
    const chunkData = await chunkRes.json();
    if (chunkData.error) throw new Error(chunkData.error);
    result.chunks = chunkData.output;
    result.numChunks = chunkData.num_chunks ?? (Array.isArray(chunkData.output) ? chunkData.output.length : 0);
    setStep("chunking", { state: "done" });

    // 5. Store
    setStep("store", { state: "running" });
    const storeRes = await fetch("/api/my/rag/store", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chunks: result.chunks, filename: entry.name, categoria: selectedCategory }),
    });
    if (!storeRes.ok) throw new Error(`Store failed: ${storeRes.status}`);
    const storeData = await storeRes.json();
    if (storeData.error) throw new Error(storeData.error);
    result.numStored = storeData.num_stored;
    result.docId = storeData.doc_id;
    setStep("store", { state: "done" });

    return result;
  };

  const processAll = async () => {
    if (!selectedCategory) {
      toast.error("Please select a category first");
      return;
    }
    if (files.length === 0) {
      toast.error("No files to process");
      return;
    }

    setProcessing(true);
    setPipelineResult(null);

    for (let i = 0; i < files.length; i++) {
      setCurrentFileIdx(i);
      try {
        const result = await processFile(files[i]);
        setPipelineResult(result);
        toast.success(`Processed "${files[i].name}" successfully`);
      } catch (e: any) {
        const currentRunning = STEPS.find((s) => stepStatuses[s]?.state === "running");
        if (currentRunning) setStep(currentRunning, { state: "error" });
        toast.error(`Error processing "${files[i].name}": ${e.message || e}`);
        break;
      }
    }

    setProcessing(false);
    setCurrentFileIdx(-1);
    setFiles([]);
    await fetchIndexedDocs(selectedCategory);
  };

  /* ================================================================ */
  /*  Chat: Documents list                                            */
  /* ================================================================ */

  useEffect(() => {
    const loadChatDocuments = async () => {
      try {
        const res = await fetch("/api/my/rag/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            categoria: chatCategory === "All" ? "" : chatCategory,
          }),
        });
        if (res.ok) {
          const data = await res.json();
          const docs = data.documents || data.output || [];
          setChatDocuments(Array.isArray(docs) ? docs : []);
        }
      } catch {
        setChatDocuments([]);
      }
    };
    loadChatDocuments();
  }, [chatCategory]);

  /* ================================================================ */
  /*  Chat: Suggested questions                                       */
  /* ================================================================ */

  useEffect(() => {
    const loadSuggested = async () => {
      if (chatCategory === "All" || chatDocuments.length === 0) {
        setSuggestedQuestions([]);
        return;
      }
      setQuestionsLoading(true);
      try {
        const res = await fetch("/api/my/rag/questions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ categoria: chatCategory, max: 3 }),
        });
        if (res.ok) {
          const data = await res.json();
          const qs = (data.questions || []).map((q: any) => ({ question: q.question, filename: q.filename }));
          setSuggestedQuestions(qs);
        } else {
          setSuggestedQuestions([]);
        }
      } catch {
        setSuggestedQuestions([]);
      } finally {
        setQuestionsLoading(false);
      }
    };
    loadSuggested();
  }, [chatCategory, chatDocuments]);

  /* ================================================================ */
  /*  Chat: Send message                                              */
  /* ================================================================ */

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async (userInput: string) => {
    if (isLoading || !userInput.trim()) return;

    const userMessage: Message = {
      id: Date.now(),
      role: "user",
      content: userInput.trim(),
    };

    const history = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsLoading(true);

    const assistantId = Date.now() + 1;
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "" },
    ]);

    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch("/api/my/v1/ragchat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input: userInput.trim(),
          categoria: chatCategory === "All" ? "" : chatCategory,
          messages: history,
          top_k: 15,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      const content = data.output || "No response received";
      const sources: Source[] = (data.sources || []).filter(
        (s: Source) => s.score > 0.01
      );

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content, sources } : m
        )
      );
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId && !m.content
              ? { ...m, content: "(stopped)" }
              : m
          )
        );
      } else {
        toast.error(
          error instanceof Error ? error.message : "Failed to send message"
        );
        setMessages((prev) => prev.filter((m) => m.id !== assistantId));
      }
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleChatSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(inputValue);
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleReset = () => {
    handleStop();
    setMessages([]);
  };

  /* ================================================================ */
  /*  Helpers                                                         */
  /* ================================================================ */

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const stepBarColor = (status: StepStatus) => {
    if (status.state === "done") return "bg-green-500";
    if (status.state === "running") return "bg-blue-500 animate-pulse";
    if (status.state === "error") return "bg-red-500";
    return "bg-gray-200";
  };

  const placeholderText =
    chatCategory === "All"
      ? "Question about all documents..."
      : `Question about ${chatCategory}...`;

  /* ================================================================ */
  /*  Render: Ingest Tab                                              */
  /* ================================================================ */

  const renderIngestTab = () => (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-4xl space-y-6">

        {/* Category selector */}
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium whitespace-nowrap">Category:</label>
          <select
            className="flex h-9 w-full max-w-xs rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
          >
            <option value="">All</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <Button variant="outline" size="sm" onClick={() => setShowManage((v) => !v)}>
            <Settings className="h-4 w-4 mr-1" /> Manage
          </Button>
        </div>

        {/* Category management panel */}
        {showManage && (
          <div className="border rounded-lg p-4 space-y-4 bg-card">
            <h3 className="font-semibold text-sm">Manage Categories</h3>

            {/* Add */}
            <div className="flex gap-2">
              <Input
                placeholder="New category name"
                value={newCatName}
                onChange={(e) => setNewCatName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCategory()}
                className="max-w-xs"
              />
              <Button size="sm" onClick={addCategory} disabled={catLoading || !newCatName.trim()}>
                {catLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4 mr-1" />}
                Add
              </Button>
            </div>

            {/* List */}
            {categories.length === 0 ? (
              <p className="text-sm text-muted-foreground">No categories yet.</p>
            ) : (
              <ul className="space-y-2">
                {categories.map((cat) => (
                  <li key={cat} className="flex items-center gap-2 text-sm">
                    {editingCat === cat ? (
                      <>
                        <Input
                          value={editCatName}
                          onChange={(e) => setEditCatName(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && renameCategory(cat)}
                          className="h-7 max-w-xs text-sm"
                          autoFocus
                        />
                        <Button size="sm" variant="ghost" onClick={() => renameCategory(cat)} disabled={catLoading}>
                          Save
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditingCat(null)}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <>
                        <span className="flex-1">{cat}</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setEditingCat(cat);
                            setEditCatName(cat);
                          }}
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => deleteCategory(cat)}>
                          <Trash2 className="h-3 w-3 text-red-500" />
                        </Button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Drag & Drop Upload Zone */}
        <div
          className={`relative rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
            dragOver ? "border-blue-500 bg-blue-50" : "border-muted-foreground/25"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <Upload className="mx-auto h-10 w-10 text-muted-foreground mb-3" />
          <p className="text-sm font-medium">Drag & drop PDF files here, or click to browse</p>
          <p className="text-xs text-muted-foreground mt-1">Only .pdf files accepted</p>
        </div>

        {/* File list */}
        {files.length > 0 && (
          <div className="space-y-2">
            {files.map((f, idx) => (
              <div
                key={`${f.name}-${idx}`}
                className="flex items-center justify-between rounded border px-3 py-2 text-sm bg-card"
              >
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{f.name}</span>
                  <span className="text-muted-foreground">({formatSize(f.size)})</span>
                </div>
                <Button size="sm" variant="ghost" onClick={() => removeFile(idx)} disabled={processing}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}

            <Button
              onClick={processAll}
              disabled={processing || !selectedCategory}
              className="w-full"
            >
              {processing ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Processing {currentFileIdx + 1}/{files.length}...
                </>
              ) : (
                <>Process All ({selectedCategory || "select category"})</>
              )}
            </Button>
            {!selectedCategory && (
              <p className="text-xs text-red-500">Please select a category before processing.</p>
            )}
          </div>
        )}

        {/* Pipeline progress bars */}
        {(processing || STEPS.some((s) => stepStatuses[s].state !== "pending")) && (
          <div className="space-y-1">
            <div className="flex gap-1">
              {STEPS.map((step) => (
                <div key={step} className="flex-1">
                  <div className={`h-3 rounded ${stepBarColor(stepStatuses[step])}`} />
                </div>
              ))}
            </div>
            <div className="flex gap-1">
              {STEPS.map((step) => (
                <div key={step} className="flex-1 text-center">
                  <span className="text-[10px] text-muted-foreground">{STEP_LABELS[step]}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Result after store */}
        {pipelineResult && pipelineResult.docId && (
          <div className="border rounded-lg p-4 space-y-3 bg-card">
            <p className="text-sm font-semibold text-green-700">
              Stored: {pipelineResult.numStored} chunks (doc: {pipelineResult.docId})
            </p>

            <Accordion type="single" collapsible value={resultAccordion} onValueChange={setResultAccordion}>
              <AccordionItem value="extracted-text">
                <AccordionTrigger className="text-sm">
                  <div className="flex items-center gap-2">
                    <ChevronDown className="h-4 w-4" />
                    Extracted text
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="max-h-64 overflow-y-auto whitespace-pre-wrap text-xs p-3 bg-muted rounded">
                    {pipelineResult.extractedText}
                  </div>
                </AccordionContent>
              </AccordionItem>

              <AccordionItem value="chunks">
                <AccordionTrigger className="text-sm">
                  <div className="flex items-center gap-2">
                    <ChevronDown className="h-4 w-4" />
                    {pipelineResult.numChunks} chunks
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="max-h-96 overflow-y-auto space-y-2">
                    {pipelineResult.chunks?.map((chunk, idx) => (
                      <div key={idx} className="border-l-4 border-blue-500 p-3 bg-muted rounded-r text-xs whitespace-pre-wrap">
                        <span className="font-semibold text-blue-700 block mb-1">Chunk {idx + 1}</span>
                        {chunk}
                      </div>
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        )}

        {/* Indexed Documents */}
        <div className="border rounded-lg p-4 space-y-3 bg-card">
          <h3 className="text-sm font-semibold">
            Indexed documents in {selectedCategory || "All"} ({indexedDocs.length}):
          </h3>
          {docsLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading...
            </div>
          ) : indexedDocs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No documents indexed yet.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {indexedDocs.map((doc) => (
                <div
                  key={doc.doc_id}
                  className="inline-flex items-center gap-2 rounded-full border bg-muted px-3 py-1 text-xs"
                >
                  <FileText className="h-3 w-3" />
                  <span className="font-medium">{doc.filename}</span>
                  <span className="text-muted-foreground">({doc.num_chunks} chunks)</span>
                  <button
                    onClick={() => deleteDoc(doc)}
                    className="ml-1 rounded-full p-0.5 hover:bg-red-100 transition-colors"
                    title="Delete document"
                  >
                    <X className="h-3 w-3 text-red-500" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );

  /* ================================================================ */
  /*  Render: Chat Tab                                                */
  /* ================================================================ */

  const renderChatTab = () => (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Chat header bar */}
      <div className="flex items-center border-b px-4 py-2 gap-2">
        <Button variant="outline" size="sm" onClick={handleReset}>
          <RotateCcw className="h-4 w-4" />
        </Button>
        <select
          value={chatCategory}
          onChange={(e) => setChatCategory(e.target.value)}
          className="rounded-md border bg-background px-3 py-1.5 text-sm"
        >
          <option value="All">All</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
        <div className="flex-1" />
      </div>

      {/* Document List Bar */}
      <div className="border-b bg-muted/30 px-4 py-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted-foreground whitespace-nowrap">
            Indexed documents ({chatDocuments.length}):
          </span>
          {chatDocuments.map((doc, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-900 dark:text-blue-200"
            >
              <FileText className="h-3 w-3" />
              {doc.filename}
              <span className="text-blue-600 dark:text-blue-300">
                ({doc.chunks})
              </span>
            </span>
          ))}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-muted-foreground max-w-md">
              <p className="text-lg font-semibold">RAG Chat</p>
              <p className="text-sm">
                Select a category and ask questions about your documents
              </p>
              {chatDocuments.length === 0 && (
                <p className="mt-4 text-sm text-orange-500 font-medium">
                  No documents indexed for this category.
                </p>
              )}
              {chatCategory !== "All" && chatDocuments.length > 0 && (
                <div className="mt-6 space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">
                    Suggested questions:
                  </p>
                  {questionsLoading ? (
                    <div className="flex items-center justify-center gap-2 text-sm">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Generating...
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-2 justify-center">
                      {suggestedQuestions.map((q, i) => (
                        <button
                          key={i}
                          onClick={() => sendMessage(q.question)}
                          className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground transition-colors text-left"
                        >
                          <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                          <span>{q.question}</span>
                          <span className="text-xs text-muted-foreground">{q.filename.replace(/\.pdf$/, "").replace(/^[A-Za-z]+_/, "")}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {chatDocuments.length === 0 && (
              <div className="rounded-md bg-orange-50 dark:bg-orange-950 border border-orange-200 dark:border-orange-800 px-4 py-2 text-sm text-orange-700 dark:text-orange-300">
                No documents indexed for this category.
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id}>
                <div
                  className={`flex ${
                    message.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  <div
                    className={`max-w-[85%] overflow-x-auto rounded-lg px-4 py-2 ${
                      message.role === "user"
                        ? "bg-blue-600 text-white"
                        : "bg-muted text-foreground"
                    }`}
                  >
                    {message.role === "assistant" ? (
                      <div
                        className="prose prose-sm dark:prose-invert max-w-none [&_table]:text-xs [&_table]:w-full [&_th]:px-2 [&_td]:px-2"
                        dangerouslySetInnerHTML={{
                          __html: marked.parse(message.content) as string,
                        }}
                      />
                    ) : (
                      <p className="whitespace-pre-wrap">{message.content}</p>
                    )}
                  </div>
                </div>
                {/* Sources */}
                {message.role === "assistant" &&
                  message.sources &&
                  message.sources.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-1.5 ml-1">
                      {message.sources.map((src, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900 dark:text-blue-200"
                        >
                          <FileText className="h-3 w-3" />
                          {src.filename}
                          <span className="text-blue-500 dark:text-blue-300">
                            {(src.score * 100).toFixed(0)}%
                          </span>
                        </span>
                      ))}
                    </div>
                  )}
              </div>
            ))}
            {/* Loading indicator */}
            {isLoading &&
              messages.length > 0 &&
              messages[messages.length - 1]?.content === "" && (
                <div className="flex justify-start">
                  <div className="rounded-lg bg-muted px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="flex space-x-1">
                        <span className="animate-bounce text-lg font-bold">.</span>
                        <span className="animate-bounce text-lg font-bold" style={{ animationDelay: "0.1s" }}>.</span>
                        <span className="animate-bounce text-lg font-bold" style={{ animationDelay: "0.2s" }}>.</span>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      Searching documents and generating response...
                    </p>
                    <Button
                      variant="destructive"
                      size="sm"
                      className="mt-2"
                      onClick={handleStop}
                    >
                      <Square className="h-3 w-3 mr-1" />
                      Stop
                    </Button>
                  </div>
                </div>
              )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="border-t p-4">
        <div className="mx-auto max-w-3xl">
          <form onSubmit={handleChatSubmit} className="flex gap-2">
            <Input
              type="text"
              placeholder={placeholderText}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              disabled={isLoading}
              className="flex-1"
            />
            {isLoading ? (
              <Button
                type="button"
                variant="destructive"
                size="icon"
                onClick={handleStop}
              >
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                type="submit"
                size="icon"
                disabled={!inputValue.trim()}
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
            )}
          </form>
        </div>
      </div>
    </div>
  );

  /* ================================================================ */
  /*  Main render                                                     */
  /* ================================================================ */

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Title + Tabs */}
      <header className="border-b">
        <div className="flex items-center justify-start px-4 pt-3 pb-0">
          <h1 className="text-xl font-semibold text-foreground">RAG Document System</h1>
        </div>
        <div className="flex justify-center gap-0 px-4">
          <button
            onClick={() => setActiveTab("ingest")}
            className={`px-6 py-2 text-sm font-medium transition-colors border-b-2 ${
              activeTab === "ingest"
                ? "border-orange-600 text-orange-600"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Ingest
          </button>
          <button
            onClick={() => setActiveTab("chat")}
            className={`px-6 py-2 text-sm font-medium transition-colors border-b-2 ${
              activeTab === "chat"
                ? "border-orange-600 text-orange-600"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Chat
          </button>
        </div>
      </header>

      {/* Tab content */}
      {activeTab === "ingest" ? renderIngestTab() : renderChatTab()}
    </div>
  );
};

export default Index;
