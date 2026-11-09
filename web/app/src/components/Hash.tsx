// A full hash, wrapped only between groups of eight characters so a line never splits a group.
// The groups are separate inline boxes with a margin, not spaces: copying still gives the exact hash.
export function Hash({ value, prefix }: { value: string; prefix?: string }) {
  const groups = value.match(/.{1,8}/g) ?? [value];
  return (
    <code className="hash hash-groups" title={value}>
      {prefix && <span className="hash-prefix">{prefix} </span>}
      {groups.map((g, i) => <span key={i}>{g}</span>)}
    </code>
  );
}
