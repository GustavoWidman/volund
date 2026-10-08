#ifndef RANGE_ENGINE_CONTRACT_H
#define RANGE_ENGINE_CONTRACT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct Event { uint64_t timestamp; uint32_t stream; int32_t value; };
struct RangeQuery { uint64_t lo; uint64_t hi; uint32_t stream; uint32_t reserved; };
struct RangeResult { uint64_t count; int64_t sum; int32_t minimum; int32_t maximum; };
int engine_run(const struct Event *events, size_t event_count,
               const struct RangeQuery *queries, size_t query_count,
               struct RangeResult *results);
#ifdef __cplusplus
}
static_assert(sizeof(Event)==16);
static_assert(sizeof(RangeQuery)==24);
static_assert(sizeof(RangeResult)==24);
#endif
#endif
