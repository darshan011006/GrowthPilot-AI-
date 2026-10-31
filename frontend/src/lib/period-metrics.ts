import type { Analytics } from "@/lib/types";

type Values = { reach: number | null; interactions: number | null; saves: number | null; engagement: number | null; posts: number };
export type PeriodChange = { percent: number | null; isNew: boolean };

export interface PeriodMetrics {
  current: Values;
  previous: Values;
  change: Record<keyof Values, PeriodChange>;
  hasData: boolean;
}

export function latestPeriodEnd(items: Analytics["items"]): number | null {
  let latest: number | null = null;
  for (const item of items) {
    if (!item.published_at) continue;
    const time = new Date(item.published_at).getTime();
    if (Number.isFinite(time) && (latest === null || time > latest)) latest = time;
  }
  return latest === null ? null : latest + 1;
}

function empty(): Values {
  return { reach: 0, interactions: 0, saves: 0, engagement: null, posts: 0 };
}

function aggregate(items: Analytics["items"], start: number, end: number): Values {
  const result = empty();
  let reachForRate = 0;
  let interactionsForRate = 0;
  let reachCount = 0;
  let interactionCount = 0;
  let savesCount = 0;
  for (const item of items) {
    if (!item.published_at) continue;
    const time = new Date(item.published_at).getTime();
    if (!Number.isFinite(time) || time < start || time >= end) continue;
    result.posts += 1;
    if (item.reach !== null) { result.reach = (result.reach || 0) + item.reach; reachCount += 1; }
    if (item.interactions !== null) { result.interactions = (result.interactions || 0) + item.interactions; interactionCount += 1; }
    if (item.saves !== null) { result.saves = (result.saves || 0) + item.saves; savesCount += 1; }
    if (item.reach !== null && item.reach > 0 && item.interactions !== null) {
      reachForRate += item.reach;
      interactionsForRate += item.interactions;
    }
  }
  if (!reachCount) result.reach = null;
  if (!interactionCount) result.interactions = null;
  if (!savesCount) result.saves = null;
  result.engagement = reachForRate ? interactionsForRate / reachForRate : null;
  return result;
}

function compare(current: number | null, previous: number | null): PeriodChange {
  if (current === null || previous === null) return { percent: null, isNew: false };
  if (previous === 0) return { percent: null, isNew: current > 0 };
  return { percent: (current - previous) / Math.abs(previous) * 100, isNew: false };
}

/** Compare the latest rolling 30 days with the 30 days immediately before them. */
export function periodMetrics(items: Analytics["items"], now = latestPeriodEnd(items) ?? 0): PeriodMetrics {
  const thirtyDays = 30 * 24 * 60 * 60 * 1000;
  const current = aggregate(items, now - thirtyDays, now + 1);
  const previous = aggregate(items, now - 2 * thirtyDays, now - thirtyDays);
  const hasData = current.posts > 0 || previous.posts > 0;
  const change = {
    reach: compare(current.reach, previous.reach),
    interactions: compare(current.interactions, previous.interactions),
    saves: compare(current.saves, previous.saves),
    engagement: compare(current.engagement, previous.engagement),
    posts: compare(current.posts, previous.posts),
  };
  return { current, previous, change, hasData };
}
