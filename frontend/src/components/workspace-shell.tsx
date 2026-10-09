"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "./icon";

export function WorkspaceShell({ children, active = "cases", preview = false, account }: {
  children: ReactNode; active?: "cases" | "access"; preview?: boolean; account?: ReactNode;
}) {
  return (
    <div className="workspace-app">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="app-header">
        <Link className="app-brand" href="/" aria-label="Central Finance case board"><span className="brand-symbol">cf</span><span>Central Finance<span className="brand-description">Exception workspace</span></span></Link>
        <div className="header-right">
          {account || <Link className="account-link" href="/access"><Icon name="lock" size={15} /><span>Workspace access</span></Link>}
        </div>
      </header>
      <nav className="app-nav" aria-label="Main navigation">
        <div className="nav-links"><Link href="/" className={active === "cases" && !preview ? "nav-item selected" : "nav-item"} aria-current={active === "cases" && !preview ? "page" : undefined}><Icon name="cases" size={17} />Case board</Link><Link href="/preview" className={preview ? "nav-item selected" : "nav-item"} aria-current={preview ? "page" : undefined}><Icon name="preview" size={17} />Design preview</Link></div>
        <span className="environment-label"><span />Synthetic environment</span>
      </nav>
      <main id="main-content" className="workspace-main">{children}</main>
      <footer className="app-footer"><span>Central Finance exception management</span><span>{preview ? "Design examples only. No changes are saved." : "Private workspace. SAP actions are simulated."}</span></footer>
    </div>
  );
}
