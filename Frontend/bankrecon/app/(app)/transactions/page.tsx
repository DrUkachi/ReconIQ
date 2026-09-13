import { TransactionsTable } from "@/app/components/dashboard/transactions-table";
import { getAllTransactions, requireSession } from "@/app/lib/server-api";

type SearchParams = Record<string, string | string[] | undefined>;

const MATCH_STATUSES = ["AUTO", "CONFIRMED", "REVIEW", "IN_CASE", "UNMATCHED"] as const;
const RESOLUTION_STATUSES = ["PENDING", "RESOLVED"];
const PAGE_SIZES = [10, 25, 50, 100] as const;

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

// Only well-formed values reach the backend, so a hand-edited URL shows a filtered
// table instead of a validation error page.
function backendQuery(raw: SearchParams) {
  const query = new URLSearchParams();
  const page = Number.parseInt(first(raw.page) ?? "", 10);
  if (page > 1) query.set("page", String(page));

  const size = Number.parseInt(first(raw.page_size) ?? "", 10);
  query.set("page_size", String((PAGE_SIZES as readonly number[]).includes(size) ? size : 25));

  const resolution = first(raw.resolution_status)?.toUpperCase();
  if (resolution && RESOLUTION_STATUSES.includes(resolution)) query.set("resolution_status", resolution);

  const status = first(raw.status)?.toUpperCase();
  if (status && (MATCH_STATUSES as readonly string[]).includes(status)) query.set("status", status);

  const currency = first(raw.currency)?.toUpperCase();
  if (currency && /^[A-Z]{3}$/.test(currency)) query.set("currency", currency);

  const q = first(raw.q)?.trim().slice(0, 100);
  if (q) query.set("q", q);

  return query;
}

export default async function TransactionsPage({
  searchParams,
}: {
  searchParams?: Promise<SearchParams> | SearchParams;
}) {
  await requireSession();
  const resolved = searchParams instanceof Promise ? await searchParams : (searchParams ?? {});
  const query = backendQuery(resolved);
  const data = await getAllTransactions(query);

  return <TransactionsTable data={data} query={query.toString()} />;
}
