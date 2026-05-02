"use client";

import { use } from "react";

import { GoogleSheetEditor } from "@/app/(app)/google/_components/google-sheet-editor";

export default function GoogleSheetPage({
  params,
}: {
  params: Promise<{ spreadsheetId: string }>;
}) {
  const { spreadsheetId } = use(params);
  return <GoogleSheetEditor spreadsheetId={spreadsheetId} />;
}

