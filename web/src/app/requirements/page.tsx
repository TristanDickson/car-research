"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Loading } from "@/components/ui";

/** The page moved: saved searches and settings now live at /settings. */
export default function RequirementsMoved() {
  const router = useRouter();
  useEffect(() => { router.replace("/settings"); }, [router]);
  return <Loading />;
}
