import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { buildUrl } from "@/api/client";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { QualityBar } from "@/components/ui/QualityBar";
import { StatusBadge } from "@/components/ui/primitives";
import { validateFile } from "@/features/datasets/UploadPanel";
import { pipelineSchema } from "@/features/pipelines/PipelineEditorPage";
import { IssueList } from "@/features/quality/components";
import { fmtBytes, fmtDuration, formatCell, scoreTone } from "@/lib/format";

const scores = { completeness: 99.5, validity: 80, uniqueness: 100, consistency: 92 };

describe("QualityBar", () => {
  it("sizes segments by documented weight and fills by score", () => {
    render(<QualityBar scores={scores} />);
    const bar = screen.getByRole("img");
    const segments = Array.from(bar.children) as HTMLElement[];
    expect(segments.map((s) => s.style.flexGrow)).toEqual(["0.3", "0.3", "0.2", "0.2"]);
    expect((segments[1].firstChild as HTMLElement).style.width).toBe("80%");
    expect(bar).toHaveAccessibleName(/Validity 80.0 percent/);
    expect(screen.getByText("Completeness (30%)")).toBeInTheDocument();
  });
});

describe("validateFile", () => {
  const file = (name: string, size: number) => new File([new Uint8Array(size)], name);
  it("accepts allowed files within the limit", () => {
    expect(validateFile(file("sales.CSV", 10), 1, [".csv", ".xlsx"])).toBeNull();
  });
  it("rejects other extensions, empty and oversized files", () => {
    expect(validateFile(file("x.exe", 10), 1, [".csv"])).toMatch(/Only .csv/);
    expect(validateFile(file("x.csv", 0), 1, [".csv"])).toMatch(/empty/);
    expect(validateFile(file("x.csv", 2 * 1024 * 1024), 1, [".csv"])).toMatch(/1 MB limit/);
  });
});

describe("pipelineSchema", () => {
  it("requires a dataset and a name", () => {
    const r = pipelineSchema.safeParse({ dataset_id: 0, name: "  " });
    expect(r.success).toBe(false);
    if (!r.success) expect(r.error.issues.map((i) => i.path[0]).sort()).toEqual(["dataset_id", "name"]);
    expect(pipelineSchema.safeParse({ dataset_id: 3, name: "Clean" }).success).toBe(true);
  });
});

describe("IssueList", () => {
  const issue = (id: number, dimension: string, severity: string) => ({
    id, check_code: "x", dimension, severity, column_key: null, column_name: "Region", affected_rows: 5,
    affected_ratio: 0.05, message: `Issue ${id}`, recommendation: "Fix it", examples: ["' a '"],
  });
  it("filters findings by dimension", async () => {
    const issues = [issue(1, "completeness", "high"), issue(2, "consistency", "low")] as never;
    render(<IssueList issues={issues} rowCount={100} />);
    expect(screen.getByText("Issue 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Consistency/ }));
    expect(screen.queryByText("Issue 1")).not.toBeInTheDocument();
    expect(screen.getByText("Issue 2")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Validity/ })).toBeDisabled();
  });
  it("shows an explicit empty state", () => {
    render(<IssueList issues={[]} rowCount={1} />);
    expect(screen.getByText(/No issues were detected/)).toBeInTheDocument();
  });
});

describe("ChartFrame", () => {
  it("offers a table view of the same values", async () => {
    render(<ChartFrame title="Revenue" table={{ headers: ["Region", "Revenue"], rows: [["Central", 1234.5]] }}><div>chart</div></ChartFrame>);
    expect(screen.getByText("chart")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Table" }));
    expect(screen.getByRole("cell", { name: "1,234.5" })).toBeInTheDocument();
  });
});

describe("StatusBadge and formatting", () => {
  it("labels status with text, not colour alone", () => {
    render(<MemoryRouter><StatusBadge status="failed" /></MemoryRouter>);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
  it("formats values", () => {
    expect(fmtBytes(2048)).toBe("2.0 KB");
    expect(fmtDuration(1500)).toBe("1.50 s");
    expect(formatCell(1234.567, "decimal")).toBe("1,234.57");
    expect(formatCell(10216.7, "decimal")).toBe("10,216.70");
    expect(formatCell(null)).toBe("");
    expect(scoreTone(98)).toBe("good");
    expect(scoreTone(85)).toBe("poor");
  });
  it("builds API URLs without empty parameters", () => {
    expect(buildUrl("/explorer/rows", { source: "raw-1", search: "", page: 2, sort: undefined }))
      .toBe("/api/explorer/rows?source=raw-1&page=2");
  });
});
