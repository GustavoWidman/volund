#include "engine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>
#if __has_include(<valgrind/callgrind.h>)
#include <valgrind/callgrind.h>
#define HAVE_CALLGRIND 1
#else
#define HAVE_CALLGRIND 0
#define CALLGRIND_START_INSTRUMENTATION ((void)0)
#define CALLGRIND_STOP_INSTRUMENTATION ((void)0)
#define CALLGRIND_ZERO_STATS ((void)0)
#define CALLGRIND_DUMP_STATS ((void)0)
#endif
using Run = int(*)(const Event*,size_t,const RangeQuery*,size_t,RangeResult*);
static std::vector<unsigned char> read_file(const std::string& p) { std::ifstream f(p,std::ios::binary); if(!f)throw std::runtime_error("cannot open fixture"); return {std::istreambuf_iterator<char>(f),{}}; }
static uint64_t u64(const std::vector<unsigned char>&v,size_t p){if(p+8>v.size())throw std::runtime_error("short fixture");uint64_t x=0;for(int i=0;i<8;i++)x|=uint64_t(v[p+i])<<(8*i);return x;}
int main(int argc,char**argv){try{
 std::string lib,in,out,mode="benchmark"; double minimum=.05; size_t cap=1024,warmups=1,fixed=0;
 for(int i=1;i<argc;i++){std::string a=argv[i];if(i+1>=argc)throw std::runtime_error("missing argument");std::string v=argv[++i];if(a=="--library")lib=v;else if(a=="--input")in=v;else if(a=="--expected")out=v;else if(a=="--mode")mode=v;else if(a=="--min-seconds")minimum=std::stod(v);else if(a=="--max-repetitions")cap=std::stoull(v);else if(a=="--warmups")warmups=std::stoull(v);else if(a=="--repetitions")fixed=std::stoull(v);else throw std::runtime_error("unknown option");}
 if(lib.empty()||in.empty()||out.empty()||cap<1||minimum<=0||!std::isfinite(minimum))throw std::runtime_error("invalid arguments");
 if(mode!="benchmark"&&mode!="profile"&&mode!="verify")throw std::runtime_error("invalid mode");
 auto ib=read_file(in),eb=read_file(out); if(ib.size()<24||memcmp(ib.data(),"RQENG001",8)||eb.size()<16||memcmp(eb.data(),"RQOUT001",8))throw std::runtime_error("bad magic");
 size_t n=u64(ib,8),q=u64(ib,16);if(n>1000000||q>4096||ib.size()!=24+n*sizeof(Event)+q*sizeof(RangeQuery)||eb.size()!=16+q*sizeof(RangeResult)||u64(eb,8)!=q)throw std::runtime_error("invalid fixture length");
 std::vector<Event> events(n);std::vector<RangeQuery> queries(q);std::vector<RangeResult> expected(q); if(n)memcpy(events.data(),ib.data()+24,n*sizeof(Event));if(q){memcpy(queries.data(),ib.data()+24+n*sizeof(Event),q*sizeof(RangeQuery));memcpy(expected.data(),eb.data()+16,q*sizeof(RangeResult));}
 const auto original_events=events;const auto original_queries=queries;std::vector<RangeResult> results(q+2);volatile uint64_t sink=0;
 void* h=dlopen(lib.c_str(),RTLD_NOW|RTLD_LOCAL);if(!h)throw std::runtime_error(dlerror());auto run=reinterpret_cast<Run>(dlsym(h,"engine_run"));if(!run)throw std::runtime_error("missing engine_run");
 if(mode=="profile"&&!HAVE_CALLGRIND)throw std::runtime_error("driver lacks Callgrind client headers");
 size_t sequence=0;
 auto call=[&](bool prof){unsigned char canary=static_cast<unsigned char>(0xa5^(++sequence*37));memset(results.data(),canary,results.size()*sizeof(RangeResult));
  auto start=std::chrono::steady_clock::now();
  if(prof){CALLGRIND_ZERO_STATS;CALLGRIND_START_INSTRUMENTATION;}
  int rc=run(events.data(),n,queries.data(),q,results.data()+1);
  if(prof){CALLGRIND_STOP_INSTRUMENTATION;}
  auto finish=std::chrono::steady_clock::now();
  if(prof){CALLGRIND_DUMP_STATS;}
  if(rc)throw std::runtime_error("engine returned "+std::to_string(rc));
  if(n&&memcmp(events.data(),original_events.data(),n*sizeof(Event)))throw std::runtime_error("events mutated");if(q&&memcmp(queries.data(),original_queries.data(),q*sizeof(RangeQuery)))throw std::runtime_error("queries mutated");
  for(size_t j=0;j<sizeof(RangeResult);j++)if(reinterpret_cast<unsigned char*>(results.data())[j]!=canary||reinterpret_cast<unsigned char*>(results.data()+q+1)[j]!=canary)throw std::runtime_error("output guard corrupted");
  if(q&&memcmp(results.data()+1,expected.data(),q*sizeof(RangeResult)))throw std::runtime_error("incorrect result");
  if(q)sink=sink^results[1].count^uint64_t(results[q].sum);return std::chrono::duration<double>(finish-start).count();};
 double elapsed=0;size_t reps=0; if(mode=="profile"||mode=="verify"){elapsed=call(mode=="profile");reps=1;}else{for(size_t i=0;i<warmups;i++)call(false);size_t batch=1;while((fixed?reps<fixed:elapsed<minimum)&&reps<cap){size_t take=std::min(batch,(fixed?std::min(cap,fixed):cap)-reps);for(size_t i=0;i<take;i++)elapsed+=call(false);reps+=take;batch=std::min(cap,batch*2);}}
 struct rusage usage{};getrusage(RUSAGE_SELF,&usage);std::cout.precision(17);std::cout<<"{\"elapsed_seconds\":"<<elapsed<<",\"seconds_per_call\":"<<elapsed/reps<<",\"repetitions\":"<<reps<<",\"sample_target_met\":"<<(elapsed>=minimum?"true":"false")<<",\"peak_rss_kib\":"<<usage.ru_maxrss<<",\"verified_calls\":"<<sequence<<",\"callgrind_headers\":"<<(HAVE_CALLGRIND?"true":"false")<<",\"sink\":"<<sink<<"}\n";dlclose(h);return 0;
 }catch(const std::exception&e){std::cerr<<"driver error: "<<e.what()<<"\n";return 2;}catch(...){std::cerr<<"driver error: unknown exception\n";return 2;}}
