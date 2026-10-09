"use client";

import Link from "next/link";
import { previewCases } from "@/lib/design-preview";
import { CaseWorklist } from "./case-worklist";
import { WorkspaceShell } from "./workspace-shell";
import { Icon } from "./icon";

export default function DesignPreview() {
  return <WorkspaceShell preview>
    <div className="page-heading"><div><div className="breadcrumb">Operations <span>/</span> Cases</div><h1>Case board</h1><p>Review document exceptions and coordinate the next action.</p></div><div className="workspace-chip"><span className="workspace-chip-dot" />Synthetic CFIN workspace</div></div>
    <div className="connection-banner preview-banner"><Icon name="preview" size={19} /><p><strong>Design preview</strong><span>Synthetic examples. Nothing is saved.</span></p></div>
    <div className="factual-preview-toolbar"><Link className="button button-secondary" href="/preview/factual">Explore factual case preview</Link></div>
    <CaseWorklist items={previewCases} preview />
  </WorkspaceShell>;
}
