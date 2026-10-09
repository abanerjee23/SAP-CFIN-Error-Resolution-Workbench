"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as React from "react";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;
export const TabsList = ({ className, ...props }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>) => <TabsPrimitive.List className={cn("flex items-center gap-1", className)} {...props} />;
export const TabsTrigger = ({ className, ...props }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) => <TabsPrimitive.Trigger className={cn("rounded-t-lg border-b-[3px] border-transparent px-3 py-3 text-sm font-medium text-[#c4cada] transition-colors hover:bg-white/5 hover:text-white data-[state=active]:border-[#b5a6ff] data-[state=active]:bg-[#6554c0] data-[state=active]:text-white sm:px-5", className)} {...props} />;
export const TabsContent = ({ className, ...props }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>) => <TabsPrimitive.Content className={cn("pt-8 outline-none", className)} {...props} />;
