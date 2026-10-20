#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>
#include <OpenMS/FORMAT/MzIdentMLFile.h>
#include <OpenMS/METADATA/PeptideIdentificationList.h>
#include <iostream>
struct R : OpenMS::Internal::XMLFile { using XMLFile::parseBuffer_; };
struct H : OpenMS::Internal::XMLHandler { H():XMLHandler("memory","1"){}; void onStartElement(const char16_t*, const OpenMS::Internal::XMLAttributes&) override{}; void onEndElement(const char16_t*) override{}; };
int main(int argc,char** argv){try {if(argc>1){std::vector<OpenMS::ProteinIdentification> p; OpenMS::PeptideIdentificationList q; OpenMS::MzIdentMLFile().load(argv[1],p,q);std::cout<<"loaded proteins="<<p.size()<<" peptides="<<q.size()<<"\n";for(auto& x:p)for(auto& y:x.getHits())std::cout<<"protein="<<y.getAccession()<<" sequence="<<y.getSequence()<<"\n";} else {R r;for(auto x:{"<root unknown:attr='1'/>","<root xmlns:a='urn:x' xmlns:b='urn:x' a:attr='1' b:attr='2'/>","<root xmlns:xml='urn:wrong'/>"}){H h;try{r.parseBuffer_(x,&h);std::cout<<"ACCEPT "<<x<<"\n";}catch(std::exception& e){std::cout<<"REJECT "<<e.what()<<"\n";}}}}catch(std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
